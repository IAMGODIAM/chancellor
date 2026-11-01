"""Live judge transport — the W5 M6 body, built lane-agnostic.

The transport seam in `api_client` was always a callable; what was
missing was a real HTTP body behind it. This module is that body, and
it is deliberately NOT a Meta client: it speaks the OpenAI-compatible
chat-completions shape, so any lane that serves that shape — NVIDIA
NIM first (the fleet's plugged judge lane), the Meta Model API when
its shape is confirmed, any other compatible endpoint — slots in by
base URL + credential resolution alone. Lane-agnosticism is a property
of the construction, and the tests prove it against two unrelated
fixture endpoints with one unmodified callable factory.

Credential discipline: a key value never appears in this module, in
code, in logs, or in an error message. Resolution order per call:

  1. an explicit `api_key` argument (the caller owns its custody);
  2. an injected `credential_attach` hook (tests, exotic lanes);
  3. the fleet credential store: `credential_connector` names a stored
     connector (default `custom.nvidia`) and the request is stamped
     through `dynamic_credentials.add_surrogate_to_request`, which
     attaches a surrogate the egress proxy exchanges for the real key
     — the key itself never enters this process. The helper is found
     on sys.path, falling back to its known fleet location (the
     connector CLI's hardcoded path for it is stale; this loader is
     the one place that knows the true one).

Grading posture: temperature defaults to 0.0 (a judge is an
instrument, not a sampler; a caller may override per call). Bounded
retries (2) apply only to transient statuses 429/502/503/504 and to
connection errors; every other failure raises `TransportError` —
fail-closed, like everything else here: a dead lane produces an
exception, never an invented response.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path

from .api_client import (
    ChatMessage,
    ChatResponse,
    MetaModelClient,
    NotConfiguredError,
    Transport,
)

# First plugged lane: NVIDIA NIM (OpenAI-compatible), the fleet's
# stored `custom.nvidia` credential, the interim-seat judge model.
NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
NIM_ULTRA_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"
NIM_CONNECTOR = "custom.nvidia"

_CREDENTIAL_MODULE_DIRS = ("/opt/muse/skills/custom-connector-setup/bin",)
_RETRY_STATUSES = frozenset({429, 502, 503, 504})
_RETRY_BACKOFF_S = (5.0, 15.0)


class TransportError(RuntimeError):
    """A live transport call failed. Carries the HTTP status when one
    exists; never carries request headers or credential material."""


def _load_surrogate_attach():
    """Import `add_surrogate_to_request` from the fleet credential
    helper, wherever it is importable from. Raises NotConfiguredError
    naming the fix (PYTHONPATH) when it cannot be found."""
    try:
        from dynamic_credentials import add_surrogate_to_request

        return add_surrogate_to_request
    except ImportError:
        pass
    for directory in _CREDENTIAL_MODULE_DIRS:
        if Path(directory, "dynamic_credentials.py").exists():
            sys.path.insert(0, directory)
            try:
                from dynamic_credentials import add_surrogate_to_request

                return add_surrogate_to_request
            except ImportError:
                continue
    raise NotConfiguredError(
        "dynamic_credentials is not importable — the credential store "
        "cannot be reached. Add /opt/muse/skills/custom-connector-setup/bin "
        "to PYTHONPATH, or pass api_key / credential_attach explicitly."
    )


def _surrogate_hook(
    connector: str, base_url: str
) -> Callable[[urllib.request.Request], None]:
    """An attach hook stamping a request via the credential store,
    scoped to the base URL's host and nothing else."""
    host = urllib.parse.urlparse(base_url).hostname or ""

    def attach(req: urllib.request.Request) -> None:
        add = _load_surrogate_attach()
        add(req, connector, allowed_hosts=[host])

    return attach


def _message_text(message: dict) -> str:
    """The assistant text of one chat-completion choice message.
    `content` may be a plain string or a list of typed parts; only
    text parts count. Reasoning traces are NOT content: a judge score
    is read from the answer, never from the model's scratch work."""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def openai_http_transport(
    base_url: str,
    *,
    api_key: str | None = None,
    credential_attach: Callable[[urllib.request.Request], None] | None = None,
    credential_connector: str | None = None,
    timeout: float = 600.0,
    temperature: float = 0.0,
) -> Transport:
    """Build a live transport callable for any OpenAI-compatible
    chat-completions endpoint. Exactly one credential source is used:
    `api_key` wins, then `credential_attach`, then the credential
    store via `credential_connector`."""
    base = base_url.rstrip("/")
    if credential_attach is not None:
        attach = credential_attach
    elif api_key is not None:

        def attach(req: urllib.request.Request) -> None:
            req.add_header("Authorization", f"Bearer {api_key}")
    elif credential_connector is not None:
        attach = _surrogate_hook(credential_connector, base)
    else:

        def attach(_req: urllib.request.Request) -> None:
            raise NotConfiguredError(
                "live transport built with no credential source: pass "
                "api_key, credential_attach, or credential_connector"
            )

    def transport(model: str, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        body: dict = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": int(kwargs.get("max_tokens", 1024)),
            "temperature": float(kwargs.get("temperature", temperature)),
        }
        for extra in ("reasoning_effort", "top_p", "seed"):
            if kwargs.get(extra) is not None:
                body[extra] = kwargs[extra]
        payload = json.dumps(body).encode("utf-8")
        attempts = 0
        while True:
            attempts += 1
            req = urllib.request.Request(
                f"{base}/chat/completions",
                data=payload,
                method="POST",
                headers={"Content-Type": "application/json"},
            )
            attach(req)
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                break
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:
                    detail = ""
                if e.code in _RETRY_STATUSES and attempts <= len(_RETRY_BACKOFF_S):
                    time.sleep(_RETRY_BACKOFF_S[attempts - 1])
                    continue
                raise TransportError(
                    f"live transport HTTP {e.code} from {base}: {detail}"
                ) from e
            except urllib.error.URLError as e:
                if attempts <= len(_RETRY_BACKOFF_S):
                    time.sleep(_RETRY_BACKOFF_S[attempts - 1])
                    continue
                raise TransportError(
                    f"live transport connection failure to {base}: {e.reason}"
                ) from e
        try:
            choice = data["choices"][0]
            text = _message_text(choice["message"])
        except (KeyError, IndexError, TypeError) as e:
            raise TransportError(
                f"live transport returned a malformed chat completion from {base}"
            ) from e
        return ChatResponse(
            text=text,
            model=data.get("model") or model,
            usage=data.get("usage") or {},
            raw={
                "id": data.get("id"),
                "finish_reason": choice.get("finish_reason"),
                "attempts": attempts,
            },
        )

    return transport


def nim_client(meter=None, timeout: float = 600.0):
    """A client on the first plugged lane: NIM via the stored
    `custom.nvidia` credential. The Judge does not know or care which
    lane this is — that is the interface's whole point."""
    return MetaModelClient(
        base_url=NIM_BASE_URL,
        api_key="",
        transport=openai_http_transport(
            NIM_BASE_URL, credential_connector=NIM_CONNECTOR, timeout=timeout
        ),
        meter=meter,
    )
