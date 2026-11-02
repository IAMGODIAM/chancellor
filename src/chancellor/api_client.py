"""Meta Model API client interface.

Base URL and API key come from the environment:
    META_MODEL_API_BASE_URL, META_MODEL_API_KEY

Both are claimed at hackathon kickoff (Mon Oct 26, 2026); until then the
client runs against an injectable transport — the offline fake below —
so every other component can be built and tested without live access.
The live HTTP transport (Stage W5 M6) has landed behind this same
seam as `chancellor.live_transport`: a lane-agnostic OpenAI-compatible
body — NIM is the first plugged lane — and the cost meter below wraps
every transport call, so live usage is metered the moment the body
slots in. Placeholder values only; never hardcode a real key.

Model column discipline (Council AM-5): only exact, versioned model IDs
live here. ``muse-wonder-full`` does not exist as an API model and is
deliberately absent.

Cost metering (Stage W1 item 7): every transport response's usage is
accumulated by :class:`CostMeter`, priced from PRICE_TABLE at the
transport — never from a worker's self-report (a transport-reported
``cost_usd`` is kept as advisory only). Lanes (Council AM-9vi):
``canonical`` (Meta Standard — counts against the reported-runs
ceiling: $40 planning target, $60 hard stop per EA-5),
``contributor`` (Meta Contributor tier — priced for the record,
excluded from the ceiling), ``nvidia`` (dev/overflow lane,
$0 against the credit), ``fake`` (offline stand-in, $0).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

PLACEHOLDER_KEY = "REPLACE_AT_KICKOFF"

# Model identifiers — exact versioned IDs only (AM-5).
MUSE_SPARK = "muse-spark-1.3"
MUSE_SPARK_CONTRIBUTOR = "muse-spark-1.3-contributor"
MUSE_WONDER = "muse-wonder-1.0"
MUSE_IMAGE = "muse-image-1.0"
SAM_3_1 = "sam-3.1"
MUSE_GLIMMER = "meta/muse-glimmer-30b"  # NVIDIA dev/overflow lane

MODEL_IDS: tuple[str, ...] = (
    MUSE_SPARK,
    MUSE_SPARK_CONTRIBUTOR,
    MUSE_WONDER,
    MUSE_IMAGE,
    SAM_3_1,
    MUSE_GLIMMER,
)

ENV_BASE_URL = "META_MODEL_API_BASE_URL"
ENV_API_KEY = "META_MODEL_API_KEY"

# Council AM-9vi: canonical-lane spend ceiling for reported runs + demo.
# Executive amendment EA-5 (Executive Council, 2026-10-29): the planning
# target stays $40; the hard stop is $60 (worst-case all-Wonder program
# math is ~$45, so the $40 line could bind in a pessimistic variant).
CANONICAL_TARGET_USD = 40.0
CANONICAL_CEILING_USD = 60.0

LANE_CANONICAL = "canonical"
LANE_CONTRIBUTOR = "contributor"
LANE_NVIDIA = "nvidia"
LANE_FAKE = "fake"

# USD per 1M tokens: {"input": ..., "output": ...}. Meta list prices,
# Standard mode (Scout 1, docs-derived — F-11 re-checks these against
# the first metered live day). Glimmer rides NVIDIA's free trial
# endpoint: tokens are counted, price against the credit is $0.
# One palette per price family, named once: a family's versions share a
# row object (the table is read-only — CostMeter never mutates a row).
_SPARK_PRICES = {"input": 1.25, "output": 4.25}
_CONTRIBUTOR_PRICES = {"input": 0.10, "output": 0.20}

PRICE_TABLE: dict[str, dict[str, float]] = {
    MUSE_SPARK: _SPARK_PRICES,
    "muse-spark-1.2": _SPARK_PRICES,
    "muse-spark-1.1": _SPARK_PRICES,
    MUSE_WONDER: {"input": 4.00, "output": 20.00},
    MUSE_SPARK_CONTRIBUTOR: _CONTRIBUTOR_PRICES,
    "muse-spark-1.2-contributor": _CONTRIBUTOR_PRICES,
    MUSE_GLIMMER: {"input": 0.0, "output": 0.0},
}


def lane_for_model(model: str) -> str:
    """Which budget lane a model bills against."""
    if model.endswith("-contributor"):
        return LANE_CONTRIBUTOR
    if model == MUSE_GLIMMER or model.startswith(("meta/", "nvidia/")):
        return LANE_NVIDIA
    return LANE_CANONICAL


class NotConfiguredError(RuntimeError):
    """Raised when a live call is attempted without real credentials."""


@dataclass
class ChatMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class ChatResponse:
    text: str
    model: str
    usage: dict = field(default_factory=dict)
    raw: dict | None = None


# A transport takes (model, messages, **kwargs) and returns a ChatResponse.
Transport = Callable[..., ChatResponse]


def _token_counts(usage: dict) -> tuple[int, int]:
    """(input, output) token counts from a usage dict, tolerating both
    OpenAI-style (prompt/completion) and plain (input/output) keys."""
    prompt = usage.get("prompt_tokens", usage.get("input_tokens", 0))
    completion = usage.get("completion_tokens", usage.get("output_tokens", 0))
    return int(prompt or 0), int(completion or 0)


@dataclass
class MeterEntry:
    model: str
    lane: str
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float | None  # None = model not in PRICE_TABLE (unpriced)
    advisory_cost_usd: float  # transport-reported cost_usd, if any


class CostMeter:
    """Run-level transport cost meter. The authoritative cost of a call
    is tokens x PRICE_TABLE, computed here at the transport boundary;
    anything a worker or transport *claims* the call cost is advisory."""

    def __init__(self) -> None:
        self.entries: list[MeterEntry] = []

    def record(
        self, model: str, usage: dict | None, lane: str | None = None
    ) -> MeterEntry:
        usage = usage or {}
        prompt, completion = _token_counts(usage)
        prices = PRICE_TABLE.get(model)
        cost = None
        if prices is not None:
            cost = (
                prompt * prices["input"] + completion * prices["output"]
            ) / 1_000_000
        entry = MeterEntry(
            model=model,
            lane=lane if lane is not None else lane_for_model(model),
            prompt_tokens=prompt,
            completion_tokens=completion,
            cost_usd=cost,
            advisory_cost_usd=float(usage.get("cost_usd") or 0.0),
        )
        self.entries.append(entry)
        return entry

    # ------------------------------------------------------------ reads
    def total_cost(self, lane: str | None = None) -> float:
        """Priced cost summed over entries (one lane, or all lanes)."""
        return sum(
            e.cost_usd or 0.0 for e in self.entries if lane is None or e.lane == lane
        )

    def canonical_spend(self) -> float:
        """Spend that counts against the AM-9vi ceiling."""
        return self.total_cost(LANE_CANONICAL)

    def per_lane_totals(self) -> dict[str, dict]:
        totals: dict[str, dict] = {}
        for e in self.entries:
            bucket = totals.setdefault(
                e.lane,
                {
                    "calls": 0,
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "cost_usd": 0.0,
                    "advisory_cost_usd": 0.0,
                },
            )
            bucket["calls"] += 1
            bucket["prompt_tokens"] += e.prompt_tokens
            bucket["completion_tokens"] += e.completion_tokens
            bucket["cost_usd"] += e.cost_usd or 0.0
            bucket["advisory_cost_usd"] += e.advisory_cost_usd
        return totals

    @property
    def unpriced_calls(self) -> int:
        """Calls whose model is missing from PRICE_TABLE — their true
        cost is unknown, so a burn audit must never read them as $0."""
        return sum(1 for e in self.entries if e.cost_usd is None)

    def ceiling_status(self, ceiling: float = CANONICAL_CEILING_USD) -> dict:
        """Burn-audit read against the canonical-lane ceiling."""
        spend = self.canonical_spend()
        return {
            "ceiling_usd": ceiling,
            "canonical_spend_usd": spend,
            "remaining_usd": ceiling - spend,
            "exceeded": spend > ceiling,
            "unpriced_calls": self.unpriced_calls,
        }


class MetaModelClient:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: Transport | None = None,
        meter: CostMeter | None = None,
    ):
        self.base_url = (
            base_url if base_url is not None else os.environ.get(ENV_BASE_URL, "")
        )
        self.api_key = (
            api_key if api_key is not None else os.environ.get(ENV_API_KEY, "")
        )
        self.transport = transport
        self.meter = meter if meter is not None else CostMeter()

    @property
    def configured(self) -> bool:
        return (
            bool(self.base_url)
            and bool(self.api_key)
            and self.api_key != PLACEHOLDER_KEY
        )

    def chat(self, model: str, messages: list[ChatMessage], **kwargs) -> ChatResponse:
        if self.transport is not None:
            response = self.transport(model, messages, **kwargs)
            # Meter at the transport boundary, whatever transport ran —
            # fake today, the live HTTP body in W5 behind this seam.
            lane = (
                LANE_FAKE
                if response.usage.get("fake")
                else lane_for_model(response.model or model)
            )
            self.meter.record(response.model or model, response.usage, lane=lane)
            return response
        if not self.configured:
            raise NotConfiguredError(
                f"Meta Model API not configured: set {ENV_BASE_URL} and {ENV_API_KEY}. "
                "Keys unlock at hackathon kickoff (Oct 26, 2026). "
                "Pass transport=fake_transport for offline development."
            )
        raise NotConfiguredError(
            "No transport injected, and the Meta lane's own live shape "
            "is not confirmed. For a plugged lane use "
            "chancellor.live_transport (NIM first); offline, pass "
            "transport=fake_transport."
        )


def fake_transport(model: str, messages: list[ChatMessage], **kwargs) -> ChatResponse:  # noqa: ARG001
    # Transport protocol: call options are accepted for conformance and ignored.
    """Deterministic offline stand-in. Echoes the last user message with a
    stable, clearly-marked synthetic reply so pipelines can be exercised
    end-to-end with zero credits burned."""
    last_user = next(
        (m.content for m in reversed(messages) if m.role == "user"),
        messages[-1].content if messages else "",
    )
    text = (
        f"[fake:{model}] Synthetic offline response. "
        f"Prompt received ({len(last_user)} chars). "
        "Live model wiring lands at kickoff."
    )
    return ChatResponse(
        text=text,
        model=model,
        usage={
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "cost_usd": 0.0,
            "fake": True,
        },
    )


def offline_client() -> MetaModelClient:
    """A client wired to the fake transport — the default until kickoff."""
    return MetaModelClient(base_url="", api_key="", transport=fake_transport)
