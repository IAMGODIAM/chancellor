"""Sealing service — a supervised agent never holds the signing key.

The supervisor keeps the operator's key. A supervised agent gets a
sign-only channel (an inherited socket, see ``receipts.PipeSigner``) and
asks for a checkpoint to be sealed. The service signs a checkpoint only
when it is a true description of the agent's log as it stands on disk:
the chain walks cleanly, the size, Merkle root and head hash recompute
over the entries on disk, the size never shrinks, and the entries the
previous seal committed to are still the same entries. Anything else is
refused, and a refusal reaches the agent as an error.

What this does and does not buy: the key never enters the agent's
process, its environment or its memory, and sealed history cannot be
rewritten and re-sealed. An agent can still append entries of its own to
its own log and have them sealed; it cannot make a seal over entries it
removed or changed.
"""

from __future__ import annotations

import contextlib
import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

from . import receipts

_PAYLOAD_TYPES = {
    receipts.CHECKPOINT_PAYLOAD_TYPE: receipts.CHECKPOINT_SCHEMA,
    receipts.CHECKPOINT_PAYLOAD_TYPE_V2: receipts.CHECKPOINT_SCHEMA_V2,
}


def _read_rows(path: Path) -> list[dict]:
    """Parse a JSONL file, dropping a torn final line."""
    if not path.exists():
        return []
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    rows: list[dict] = []
    for pos, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if pos == len(lines) - 1:
                break
            raise
    return rows


def parse_pae(data: bytes) -> tuple[str, bytes]:
    """Split a DSSE pre-authentication encoding into (payload type,
    payload). Raises ValueError on anything that is not one."""
    if not data.startswith(b"DSSEv1 "):
        raise ValueError("not a DSSE pre-authentication encoding")
    rest = data[len(b"DSSEv1 ") :]
    type_len_text, _, rest = rest.partition(b" ")
    type_len = int(type_len_text)
    payload_type = rest[:type_len]
    rest = rest[type_len:]
    if not rest.startswith(b" "):
        raise ValueError("malformed encoding")
    payload_len_text, _, payload = rest[1:].partition(b" ")
    if int(payload_len_text) != len(payload):
        raise ValueError("payload length does not match")
    return payload_type.decode("utf-8"), payload


class SealService:
    """Signs checkpoints for supervised agents, and only checkpoints that
    describe the agent's log truthfully (see the module docstring)."""

    def __init__(
        self, signer: receipts.Signer, log_path: Path, checkpoint_path: Path
    ) -> None:
        self._signer = signer
        self._log_path = Path(log_path)
        self._checkpoint_path = Path(checkpoint_path)
        self._lock = threading.Lock()
        self._last_size = 0
        self._last_head: str | None = None
        self._channels: list[socket.socket] = []
        self._load_last_seal()

    def _load_last_seal(self) -> None:
        """Pick up the newest seal this signer already made, so a
        relaunched agent cannot be sealed over a rewritten past."""
        try:
            envelopes = _read_rows(self._checkpoint_path)
        except (OSError, ValueError):
            return
        for envelope in reversed(envelopes):
            if receipts.checkpoint_signature_valid(envelope, self._signer):
                payload = receipts.checkpoint_payload(envelope)
                size = payload.get("log_size")
                if isinstance(size, int):
                    self._last_size = size
                    self._last_head = payload.get("head_receipt_hash")
                return

    # ---- policy -----------------------------------------------------
    def _refusal(self, data: bytes) -> str | None:
        """Why this request must be refused, or None to sign it."""
        try:
            payload_type, raw = parse_pae(data)
            schema = _PAYLOAD_TYPES.get(payload_type)
            payload: Any = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return "only checkpoint payloads are signed here"
        if schema is None or not isinstance(payload, dict):
            return "only checkpoint payloads are signed here"
        if payload.get("schema") != schema or payload.get("issuer") != (
            self._signer.key_id
        ):
            return "checkpoint schema or issuer does not match this service"
        size = payload.get("log_size")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            return "checkpoint log_size is not a count"
        try:
            state = receipts.scan_chain(_read_rows(self._log_path))
        except (receipts.ChainIntegrityError, OSError, ValueError) as exc:
            return f"the log on disk does not verify: {exc}"
        if size > len(state.leaves):
            return "checkpoint commits more entries than the log holds"
        if size < self._last_size:
            return "checkpoint would shrink the sealed history"
        if self._last_size and state.leaves[self._last_size - 1] != self._last_head:
            return "entries already sealed have changed"
        root_fn = (
            receipts.rfc9162_root
            if schema == receipts.CHECKPOINT_SCHEMA_V2
            else receipts.merkle_root
        )
        head = state.leaves[size - 1] if size else None
        if payload.get("merkle_root") != root_fn(state.leaves[:size]):
            return "checkpoint root does not match the log on disk"
        if payload.get("head_receipt_hash") != head:
            return "checkpoint head does not match the log on disk"
        return None

    def sign_request(self, data: bytes) -> bytes:
        """Sign ``data`` if policy allows. Raises receipts.SigningRefused."""
        with self._lock:
            reason = self._refusal(data)
            if reason is not None:
                raise receipts.SigningRefused(reason)
            _, raw = parse_pae(data)
            payload = json.loads(raw.decode("utf-8"))
            self._last_size = payload["log_size"]
            self._last_head = payload["head_receipt_hash"]
            return self._signer.sign(data)

    # ---- channel ----------------------------------------------------
    def _serve(self, sock: socket.socket) -> None:
        try:
            while True:
                op, body = receipts.recv_frame(sock)
                try:
                    if op == b"\x01":
                        receipts.send_frame(
                            sock, b"\x00", self._signer.key_id.encode("utf-8")
                        )
                    elif op == b"\x02":
                        receipts.send_frame(sock, b"\x00", self.sign_request(body))
                    else:
                        receipts.send_frame(sock, b"\x01", b"unknown request")
                except receipts.SigningRefused as exc:
                    receipts.send_frame(sock, b"\x01", str(exc).encode("utf-8"))
        except (ConnectionError, OSError):
            pass
        finally:
            sock.close()

    def open_channel(self) -> socket.socket:
        """A new sign-only channel. Returns the agent's end; the caller
        hands it to the agent process and closes its own copy."""
        mine, theirs = socket.socketpair()
        self._channels.append(mine)
        threading.Thread(target=self._serve, args=(mine,), daemon=True).start()
        return theirs

    def close(self) -> None:
        for sock in self._channels:
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_RDWR)
        self._channels.clear()


# Names scrubbed from the agent's environment: the operator's key and
# every other way of handing one over.
_SCRUBBED_ENV = (
    "CHANCELLOR_SUPERVISE_KEY",
    "CHANCELLOR_DEV_SIGNER_SECRET",
    receipts.VERIFY_KEY_ENV,
    receipts.SIGN_FD_ENV,
)


def agent_environment() -> dict[str, str]:
    """The environment an agent starts with: the supervisor's own, minus
    anything that could carry a signing key."""
    return {k: v for k, v in os.environ.items() if k not in _SCRUBBED_ENV}


def sealed_launcher(service: SealService):
    """A launcher that starts the agent with a sign-only channel in place
    of a key: the channel's descriptor is inherited by the agent and named
    in CHANCELLOR_SIGN_FD; the agent's environment carries no key."""
    from .supervise import ProcessHandle, _PopenHandle

    def launch(command: list[str]) -> ProcessHandle:
        theirs = service.open_channel()
        try:
            fd = theirs.fileno()
            env = {**agent_environment(), receipts.SIGN_FD_ENV: str(fd)}
            proc = subprocess.Popen(command, env=env, pass_fds=(fd,))
        finally:
            theirs.close()
        return _PopenHandle(proc)

    return launch
