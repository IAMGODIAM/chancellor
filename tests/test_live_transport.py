"""Live transport tests — offline, against scripted fixture servers.

The fixture is a real HTTP server on loopback serving canned
OpenAI-shaped completions: the transport's wire behavior (request
shape, auth header, response parsing, error posture, metering) is
exercised end-to-end with zero external calls. Two DIFFERENT fixture
endpoints with two different model ids are driven by the same
unmodified factory — the lane-agnosticism proof the L9 brief asks
for, by construction rather than by assertion.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from chancellor import api_client, live_transport
from chancellor.api_client import ChatMessage, MetaModelClient, NotConfiguredError


def _completion(text="Adequate and measured.\nSCORE: 7", model="fixture/model-1"):
    return {
        "id": "chatcmpl-fixture",
        "model": model,
        "choices": [
            {
                "finish_reason": "stop",
                "message": {"role": "assistant", "content": text},
            }
        ],
        "usage": {"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133},
    }


class _Fixture:
    """A loopback HTTP server recording requests and serving a canned
    completion (or a fixed error status)."""

    def __init__(self, response=None, status=200):
        self.requests: list[dict] = []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — BaseHTTPRequestHandler's name
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                outer.requests.append(
                    {
                        "path": self.path,
                        "headers": dict(self.headers),
                        "body": json.loads(raw) if raw else {},
                    }
                )
                if status != 200:
                    self.send_response(status)
                    self.end_headers()
                    self.wfile.write(b'{"error": "fixture failure"}')
                    return
                payload = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *args):  # silence the fixture's stderr
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fixture():
    fx = _Fixture(response=_completion())
    yield fx
    fx.close()


def test_round_trip_and_request_shape(fixture):
    transport = live_transport.openai_http_transport(
        fixture.base_url, api_key="fixture-key"
    )
    resp = transport(
        "fixture/model-1",
        [ChatMessage("system", "sys"), ChatMessage("user", "grade this")],
        max_tokens=321,
    )
    assert resp.text == "Adequate and measured.\nSCORE: 7"
    assert resp.model == "fixture/model-1"
    assert resp.usage["prompt_tokens"] == 111
    assert resp.raw["finish_reason"] == "stop"
    (req,) = fixture.requests
    assert req["path"] == "/v1/chat/completions"
    assert req["headers"]["Authorization"] == "Bearer fixture-key"
    assert req["body"]["model"] == "fixture/model-1"
    assert req["body"]["max_tokens"] == 321
    assert req["body"]["temperature"] == 0.0  # judge-lane default: deterministic
    assert req["body"]["messages"] == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "grade this"},
    ]


def test_same_factory_other_lane(fixture):
    # A second endpoint + an unrelated model id, same factory, no edits:
    # the interface carries no lane-specific code.
    transport = live_transport.openai_http_transport(
        fixture.base_url, api_key="fixture-key"
    )
    resp = transport("someone-else/model-9", [ChatMessage("user", "hi")])
    assert resp.text.endswith("SCORE: 7")
    assert fixture.requests[0]["body"]["model"] == "someone-else/model-9"


def test_attach_hook_replaces_bearer(fixture):
    seen = {}

    def hook(req):
        seen["hooked"] = True
        req.add_header("X-Fixture-Auth", "hooked")

    transport = live_transport.openai_http_transport(
        fixture.base_url, credential_attach=hook
    )
    transport("fixture/model-1", [ChatMessage("user", "hi")])
    assert seen["hooked"] is True
    headers = fixture.requests[0]["headers"]
    assert headers.get("X-Fixture-Auth") == "hooked"
    assert "Authorization" not in headers


def test_http_error_fails_closed():
    fx = _Fixture(status=500)
    try:
        transport = live_transport.openai_http_transport(
            fx.base_url, api_key="fixture-key"
        )
        with pytest.raises(live_transport.TransportError) as exc:
            transport("fixture/model-1", [ChatMessage("user", "hi")])
        assert "HTTP 500" in str(exc.value)
        assert len(fx.requests) == 1  # 500 is not a retryable status
    finally:
        fx.close()


def test_content_parts_joined():
    fx = _Fixture(
        response={
            "id": "x",
            "model": "fixture/model-1",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "Part one. "},
                            {"type": "reasoning", "text": "IGNORED"},
                            {"type": "text", "text": "SCORE: 4"},
                        ],
                    },
                }
            ],
            "usage": {},
        }
    )
    try:
        transport = live_transport.openai_http_transport(
            fx.base_url, api_key="fixture-key"
        )
        resp = transport("fixture/model-1", [ChatMessage("user", "hi")])
        assert resp.text == "Part one. SCORE: 4"
    finally:
        fx.close()


def test_no_credential_source_raises():
    transport = live_transport.openai_http_transport("http://127.0.0.1:9/v1")
    with pytest.raises(NotConfiguredError):
        transport("fixture/model-1", [ChatMessage("user", "hi")])


def test_metering_marks_nim_lane_unpriced():
    # Through the real client seam: the ultra model id bills to the
    # nvidia lane and stays UNPRICED (absent from PRICE_TABLE) — a burn
    # audit must never read an unpriced call as $0.
    fx = _Fixture(response=_completion(model=live_transport.NIM_ULTRA_MODEL))
    try:
        client = MetaModelClient(
            base_url="",
            api_key="",
            transport=live_transport.openai_http_transport(
                fx.base_url, api_key="fixture-key"
            ),
        )
        client.chat(live_transport.NIM_ULTRA_MODEL, [ChatMessage("user", "grade this")])
        (entry,) = client.meter.entries
        assert entry.lane == api_client.LANE_NVIDIA
        assert entry.cost_usd is None
        assert client.meter.unpriced_calls == 1
        assert entry.prompt_tokens == 111
    finally:
        fx.close()
