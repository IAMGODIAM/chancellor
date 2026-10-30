"""Suite B world, tools, fault injection, and the scripted agent.

The world is an explicit in-memory state the tools mutate. Tools stamp
every payload they return with a checksum of the true value; a value
fault corrupts the payload *in transit*, downstream of the stamp — so
the corruption is invisible to the worker (which never verifies) but
visible to an instrument panel that recomputes the checksum. That
asymmetry is the whole experiment: governance is what notices.

The scripted agent is deterministic — no dice anywhere in a run. Its
declared fault-susceptibility surface (its policy, stated once, here):

  * crash on any tool call      -> the run aborts (the exception
                                   propagates; the harness records it)
  * omission on a REQUIRED step -> retry once; still empty -> abort
                                   honestly (never proceed on no data)
  * timing on a REQUIRED step   -> retry once (the late result lands)
  * omission/timing on an OPTIONAL step -> skip the step, degraded
  * value fault anywhere        -> applied as-is: plausible-but-wrong
                                   data is indistinguishable to the
                                   worker. Only governance catches it.

Consequence the suite is built to expose: drift (claimed success on a
failed final state) can only be produced by value faults. Crash,
omission, and timing faults abort runs or cost score — they never make
a worker claim success on corrupted state. (Thoth's expander, checked
in every Suite B report.)
"""
from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass

from ..api_client import ChatMessage, ChatResponse, MetaModelClient
from .suite_b_tasks import StepSpec, TaskSpec

# Fault classes (Council AM-3): crash / omission / value. Timing is an
# omission SUBSPECIES with its own denominator. "Cost" is not a fault
# class — it is tested by the instrument tests, not injected here.
FAULT_CRASH = "crash"
FAULT_OMISSION = "omission"
FAULT_VALUE = "value"
SUB_PLAIN = "plain"
SUB_TIMING = "timing"


class ToolCrash(Exception):
    """An injected crash fault: the tool raised mid-task."""


class StepAborted(Exception):
    """The agent aborts a step honestly (required data never arrived)."""


def checksum_of(value: object) -> str:
    """Integrity stamp over a tool payload's true value."""
    blob = json.dumps(value, sort_keys=True, default=str).encode()
    return hashlib.sha256(blob).hexdigest()


@dataclass(frozen=True)
class FaultEntry:
    """One manifest line: inject `fault` at the `call`-th invocation of
    step `step` in task `task_id`, under manifest `manifest_id`."""
    id: str
    task_id: str
    manifest_id: str
    step: str
    call: int
    fault: str                          # crash | omission | value
    subspecies: str | None = None       # omission only: plain | timing
    transform: str | None = None        # value only: scale10 | replace
    replacement: object = None          # value/replace payload
    direct_keys: tuple[str, ...] = ()   # world keys the fault itself writes

    def to_dict(self) -> dict:
        return {"id": self.id, "task_id": self.task_id,
                "manifest_id": self.manifest_id, "step": self.step,
                "call": self.call, "fault": self.fault,
                "subspecies": self.subspecies, "transform": self.transform,
                "replacement": self.replacement,
                "direct_keys": list(self.direct_keys)}


class FaultInjector:
    """Fires manifest entries at exact (step, call) points, and keeps
    the trigger ledger: an entry whose point is never reached (the run
    halted earlier) is UNTRIGGERED and leaves every denominator."""

    def __init__(self, entries: list[FaultEntry]):
        self.entries = list(entries)
        self._by_point: dict[tuple[str, int], FaultEntry] = {
            (e.step, e.call): e for e in self.entries}
        self.triggered: list[FaultEntry] = []

    def fire(self, step: str, call: int) -> FaultEntry | None:
        entry = self._by_point.get((step, call))
        if entry is not None:
            self.triggered.append(entry)
        return entry

    def untriggered(self) -> list[FaultEntry]:
        fired = {e.id for e in self.triggered}
        return [e for e in self.entries if e.id not in fired]


class World:
    """The fake world-state: an explicit dict the tools mutate."""

    def __init__(self, seed_state: dict):
        self.state: dict = copy.deepcopy(seed_state)

    def snapshot(self) -> dict:
        return copy.deepcopy(self.state)


@dataclass
class FetchResult:
    status: str                         # ok | empty | late
    value: object = None
    checksum: str | None = None


class ToolBelt:
    """The tool boundary. Every fetch is one metered model call through
    the client (the agent 'thinks' per tool call) plus one world read,
    with the injector consulted at the boundary — AgentChaos-style:
    faults live at the shared tool layer, not inside the agent."""

    def __init__(self, world: World, injector: FaultInjector,
                 client: MetaModelClient, model: str, task_id: str):
        self.world = world
        self.injector = injector
        self.client = client
        self.model = model
        self.task_id = task_id
        self._calls: dict[str, int] = {}

    def _meter(self, step: str, note: str) -> None:
        self.client.chat(self.model, [ChatMessage(
            role="user",
            content=f"suite-b task {self.task_id} step {step}: {note}")])

    def fetch(self, step: str, source_key: str) -> FetchResult:
        call = self._calls.get(step, 0)
        self._calls[step] = call + 1
        self._meter(step, f"fetch {source_key} (call {call})")
        entry = self.injector.fire(step, call)
        if entry is not None:
            if entry.fault == FAULT_CRASH:
                raise ToolCrash(
                    f"tool crash injected at {step} call {call} "
                    f"(manifest entry {entry.id})")
            if entry.fault == FAULT_OMISSION:
                return FetchResult(
                    "late" if entry.subspecies == SUB_TIMING else "empty")
            if entry.fault == FAULT_VALUE:
                true_value = self.world.state[source_key]
                corrupted = self._corrupt(true_value, entry)
                # The stamp is over the TRUE value: corruption happened
                # in transit, after stamping. A panel that recomputes
                # the checksum over the received value sees the lie.
                return FetchResult("ok", corrupted, checksum_of(true_value))
        value = self.world.state[source_key]
        return FetchResult("ok", value, checksum_of(value))

    @staticmethod
    def _corrupt(value: object, entry: FaultEntry) -> object:
        if entry.transform == "scale10" and isinstance(value, (int, float)) \
                and not isinstance(value, bool):
            return value * 10
        if entry.transform == "replace":
            return entry.replacement
        return value


_MISSING = object()   # scratch sentinel: an optional step produced nothing


class ScriptedAgent:
    """The deterministic worker. One instance per run; CrewRunner calls
    `run_step` once per graph node. The artifact it returns NEVER carries
    scores — Suite B grades final state, externally (score provenance)."""

    def __init__(self, task: TaskSpec, world: World, belt: ToolBelt):
        self.task = task
        self.world = world
        self.belt = belt
        self.scratch: dict[str, object] = {}
        self.degraded: list[str] = []

    # -- step kinds ------------------------------------------------------
    def run_step(self, step: StepSpec) -> dict:
        handler = getattr(self, f"_step_{step.kind}")
        return handler(step)

    def _fetch_required(self, step: StepSpec) -> FetchResult:
        """Required-fetch policy: one retry on empty/late, then abort."""
        result = self.belt.fetch(step.name, step.source)
        if result.status == "ok":
            return result
        result = self.belt.fetch(step.name, step.source)
        if result.status == "ok":
            return result
        raise StepAborted(
            f"required data for step {step.name} never arrived "
            f"(last status: {result.status}) — aborting honestly")

    def _step_fetch(self, step: StepSpec) -> dict:
        if step.required:
            result = self._fetch_required(step)
        else:
            result = self.belt.fetch(step.name, step.source)
            if result.status != "ok":
                self.degraded.append(step.name)
                self.scratch[step.scratch] = _MISSING
                return {"text": f"{step.name}: no data ({result.status}) "
                                "— optional step skipped",
                        "data": {"skipped": True}}
        self.scratch[step.scratch] = result.value
        return {"text": f"{step.name}: fetched {step.source} = {result.value!r}",
                "data": {"value": result.value, "checksum": result.checksum}}

    def _step_compute(self, step: StepSpec) -> dict:
        self.belt._meter(step.name, f"compute {step.op}")
        vals = [self.scratch[name] for name in step.inputs]
        result = {"add": vals[0] + vals[1], "sub": vals[0] - vals[1],
                  "mul": vals[0] * vals[1]}[step.op]
        self.scratch[step.scratch] = result
        return {"text": f"{step.name}: {step.op}{tuple(vals)} = {result}"}

    def _step_store(self, step: StepSpec) -> dict:
        self.belt._meter(step.name, f"store {step.target}")
        value = self.scratch[step.scratch]
        self.world.state[step.target] = value
        return {"text": f"{step.name}: stored {step.target} = {value!r}",
                "data": {"key": step.target, "value": value}}

    def _step_enrich(self, step: StepSpec) -> dict:
        result = self.belt.fetch(step.name, step.source)
        if result.status != "ok":
            self.degraded.append(step.name)
            return {"text": f"{step.name}: no data ({result.status}) "
                            "— optional enrich skipped",
                    "data": {"skipped": True}}
        stored = result.value if step.mode == "copy" \
            else self.scratch["result"] * result.value
        self.world.state[step.target] = stored
        return {"text": f"{step.name}: enriched {step.target} = {stored!r}",
                "data": {"value": result.value, "checksum": result.checksum,
                         "stored": stored}}

    def _step_summarize(self, step: StepSpec) -> dict:
        self.belt._meter(step.name, "summarize")
        summary = {"claimed": "complete", "task": self.task.id,
                   "headline": self.scratch.get("result")}
        self.world.state[step.target] = summary
        return {"text": f"{self.task.id} complete: headline "
                        f"{summary['headline']!r}",
                "data": {"key": step.target, "value": summary}}


def suite_transport(model: str, messages: list[ChatMessage], **kwargs) -> ChatResponse:
    """Deterministic offline transport for Suite B. Token usage is a
    fixed function of the prompt, and Lane 2's CostMeter prices it at
    list rates — Suite B's costs are metered, never self-reported
    (Scout 3 B7). Deliberately NOT marked fake: the meter should price
    these calls as the canonical lane they stand in for."""
    prompt_tokens = sum(len(m.content) for m in messages)
    return ChatResponse(
        text=f"[suite-b:{model}] deterministic offline step response",
        model=model,
        usage={"prompt_tokens": prompt_tokens, "completion_tokens": 32})
