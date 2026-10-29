"""Eval Suite B — Long-Horizon Reliability (rebuilt, Stage W4).

The old Suite B was a coin-flip simulator: it rolled dice and reported
the dice. It has been deleted, not kept (Council AM-12c). This suite
runs REAL tasks through CrewRunner — scripted deterministic workers over
an assertable fake world (see suite_b_tasks / suite_b_world) — under a
deterministic fault manifest, in two arms:

  * governed   — CrewRunner.governed: instrument panel (including a
                 payload-integrity check), rubric, gatekeeper
  * ungoverned — CrewRunner.ungoverned: the same runner, layers off

on IDENTICAL manifests. Grading is the final-state predicate over the
world, assigned externally — workers never emit scores (score
provenance, AM-7iii). Costs come from the transport meter (Lane 2's
CostMeter), including failed runs (Scout 3 B7).

Metrics (Council AM-4 — three names, three measures):
  * DRIFT       — the run claims completion AND the final-state
                  predicate fails. The pre-registered primary metric.
  * DIVERGENCE  — a claimed run's final state differs from the clean
                  run's final state in keys beyond the fault's direct
                  effect. (Assessed on claimed runs only: on a halted
                  run, downstream difference is just the halt.)
  * DISPLACEMENT— the run claims completion, the predicate PASSES, but
                  the externally-scored outcome falls >= 20 points
                  below the clean run's score.

Fault classes (AM-3): crash / omission / value; timing is an omission
subspecies with its own denominator, never pooled silently into the
headline recovery rate. Denominators count TRIGGERED faults only —
a manifest entry whose injection point was never reached is listed as
untriggered and leaves every rate.

The claim this suite supports is narrow, and the report states it:
this runner, its governance layers on vs off, on these scripted tasks
and this deterministic manifest (AM-12d). Nothing here is comparable
to published benchmark numbers.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass, field

from ..api_client import CostMeter, MetaModelClient
from ..escalation import Gatekeeper
from ..grader import OUTPUT_RUBRIC
from ..instruments import (CheckResult, InstrumentPanel, check_non_empty,
                            check_required_keys)
from ..orchestrator import CrewRunner
from ..task_graph import TaskGraph
from .suite_b_tasks import TASKS, TaskSpec
from .suite_b_world import (FAULT_CRASH, FAULT_OMISSION, FAULT_VALUE,
                            SUB_PLAIN, SUB_TIMING, FaultEntry, FaultInjector,
                            ScriptedAgent, ToolBelt, World, checksum_of,
                            suite_transport)

WORKER_MODEL = "muse-spark-1.3"     # metered at list prices (AM-5 ID)
DEFAULT_SEED = 20261029
MANIFEST_IDS = ("value", "omit", "timing", "crash", "valueopt")
DISPLACEMENT_DROP = 20.0

NARROW_CLAIM = ("Narrow claim (AM-12d): this runner (CrewRunner), its "
                "governance layers on vs off, on Suite B's scripted tasks "
                "under the deterministic manifest below. Descriptive "
                "frontier only — not comparable to published benchmarks.")


# --------------------------------------------------------------------------
# Manifest — deterministic, hashed, printed in every report (Scout 3 B3)
# --------------------------------------------------------------------------

def manifest_hash_of(entries: list[FaultEntry]) -> str:
    blob = json.dumps([e.to_dict() for e in
                       sorted(entries, key=lambda e: e.id)],
                      sort_keys=True).encode()
    return hashlib.sha256(blob).hexdigest()


def build_manifest(seed: int = DEFAULT_SEED,
                   tasks: tuple[TaskSpec, ...] = TASKS
                   ) -> tuple[dict[tuple[str, str], list[FaultEntry]], str]:
    """The demo manifest set: five archetypes per task, chosen from the
    task's declared susceptibility surface. Deterministic in `seed` —
    same seed, same manifest, same hash."""
    manifests: dict[tuple[str, str], list[FaultEntry]] = {}
    all_entries: list[FaultEntry] = []
    for task in tasks:
        rng = random.Random(f"suite-b:{seed}:{task.id}")
        quality_expected = next(a.expected for a in task.assertions
                                if not a.predicate)
        per_task: dict[str, list[FaultEntry]] = {
            # Value fault on the first required fetch: corrupts the
            # compute and the stored result (its direct effect).
            "value": [FaultEntry(
                id=f"{task.id}-value-0", task_id=task.id,
                manifest_id="value", step="fetch_a", call=0,
                fault=FAULT_VALUE, transform="scale10",
                direct_keys=(task.result_key,))],
            # Omission on BOTH the first call and the retry: defeats
            # the worker's one-retry policy -> honest abort.
            "omit": [FaultEntry(
                id=f"{task.id}-omit-{c}", task_id=task.id,
                manifest_id="omit", step="fetch_a", call=c,
                fault=FAULT_OMISSION, subspecies=SUB_PLAIN)
                for c in (0, 1)],
            # Timing on the optional enrich: the worker skips it. The
            # missing quality key IS the fault's direct effect.
            "timing": [FaultEntry(
                id=f"{task.id}-timing-0", task_id=task.id,
                manifest_id="timing", step="enrich", call=0,
                fault=FAULT_OMISSION, subspecies=SUB_TIMING,
                direct_keys=(task.quality_key,))],
            # Crash on a required fetch (seed picks which one).
            "crash": [FaultEntry(
                id=f"{task.id}-crash-0", task_id=task.id,
                manifest_id="crash",
                step=rng.choice(["fetch_a", "fetch_b"]), call=0,
                fault=FAULT_CRASH)],
            # Value fault on the optional enrich: plausible wrong
            # quality value; the predicate cannot see it, the score can.
            "valueopt": [FaultEntry(
                id=f"{task.id}-valueopt-0", task_id=task.id,
                manifest_id="valueopt", step="enrich", call=0,
                fault=FAULT_VALUE, transform="replace",
                replacement=quality_expected + 7,
                direct_keys=(task.quality_key,))],
        }
        for manifest_id, entries in per_task.items():
            manifests[(task.id, manifest_id)] = entries
            all_entries.extend(entries)
    return manifests, manifest_hash_of(all_entries)


# --------------------------------------------------------------------------
# External grading — final-state predicate + outcome score (never the
# worker's self-report; the summary the worker stores is its CLAIM, and
# the predicate is the check on that claim)
# --------------------------------------------------------------------------

def score_state(task: TaskSpec, state: dict) -> tuple[bool, float]:
    """(predicate_pass, outcome_score 0..100) for a final world state."""
    predicate_pass = True
    earned = total = 0.0
    for a in task.assertions:
        total += a.weight
        if state.get(a.key) == a.expected:
            earned += a.weight
        elif a.predicate:
            predicate_pass = False
    return predicate_pass, round(100.0 * earned / total, 2)


def check_payload_integrity(artifact: object) -> CheckResult:
    """Governed-arm instrument: a tool payload whose checksum does not
    match its stamped value was corrupted in transit — reject it."""
    if isinstance(artifact, dict):
        data = artifact.get("data")
        if isinstance(data, dict) and "value" in data and "checksum" in data:
            ok = checksum_of(data["value"]) == data["checksum"]
            return CheckResult(
                "payload_integrity", ok,
                "" if ok else "tool payload checksum mismatch — "
                              "corrupted in transit (fail-closed)")
    return CheckResult("payload_integrity", True, "no stamped payload")


def _governed_panel() -> InstrumentPanel:
    panel = InstrumentPanel(timeout_s=None)   # pure local checks; no hang risk
    panel.register("non_empty_output", check_non_empty)
    panel.register("required_keys", check_required_keys("text"))
    panel.register("payload_integrity", check_payload_integrity)
    return panel


# --------------------------------------------------------------------------
# One run
# --------------------------------------------------------------------------

@dataclass
class RunOutcome:
    task_id: str
    arm: str
    manifest_id: str
    repeat: int
    claimed_complete: bool
    predicate_pass: bool
    outcome_score: float
    drift: bool
    divergence: bool
    diverged_keys: list[str] = field(default_factory=list)
    displacement: bool = False
    triggered: list[dict] = field(default_factory=list)
    recovered_faults: int = 0
    untriggered_ids: list[str] = field(default_factory=list)
    halted: bool = False
    halt_reason: str | None = None
    steps_executed: int = 0
    cost_usd: float = 0.0
    final_state: dict = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """A success is a claim the state backs up."""
        return self.claimed_complete and self.predicate_pass


def run_configuration(task: TaskSpec, arm: str, entries: list[FaultEntry],
                      manifest_id: str = "custom", repeat: int = 0,
                      clean_state: dict | None = None) -> RunOutcome:
    """Run one task, in one arm, under one manifest's entries."""
    world = World(task.seed_state)
    meter = CostMeter()
    client = MetaModelClient(transport=suite_transport, meter=meter)
    injector = FaultInjector(list(entries))
    belt = ToolBelt(world, injector, client, WORKER_MODEL, task.id)
    agent = ScriptedAgent(task, world, belt)
    steps_by_name = {s.name: s for s in task.steps}

    graph = TaskGraph(name=f"suiteB-{task.id}-{arm}-{manifest_id}-{repeat}")
    previous: str | None = None
    for step in task.steps:
        graph.task(step.name, step.name,
                   depends_on=[previous] if previous else [],
                   worker="agent", requires_grade=False)
        previous = step.name
    workers = {"agent": lambda node: agent.run_step(steps_by_name[node.id])}
    if arm == "governed":
        runner = CrewRunner.governed(
            graph, workers, panel=_governed_panel(), rubric=OUTPUT_RUBRIC,
            gatekeeper=Gatekeeper())
    elif arm == "ungoverned":
        runner = CrewRunner.ungoverned(graph, workers)
    else:
        raise ValueError(f"unknown arm: {arm!r}")
    report = runner.run()

    final_state = world.snapshot()
    claimed = (not report.halted) and graph.is_complete()
    predicate_pass, outcome_score = score_state(task, final_state)
    triggered = [{"id": e.id, "fault": e.fault, "subspecies": e.subspecies}
                 for e in injector.triggered]
    direct_keys = {k for e in injector.triggered for k in e.direct_keys}

    drift = claimed and not predicate_pass
    diverged_keys: list[str] = []
    if claimed and clean_state is not None:
        all_keys = set(final_state) | set(clean_state)
        diverged_keys = sorted(
            key for key in all_keys
            if key not in direct_keys
            and final_state.get(key) != clean_state.get(key))
    displacement = False
    if claimed and predicate_pass and clean_state is not None:
        _, clean_score = score_state(task, clean_state)
        displacement = outcome_score <= clean_score - DISPLACEMENT_DROP

    return RunOutcome(
        task_id=task.id, arm=arm, manifest_id=manifest_id, repeat=repeat,
        claimed_complete=claimed, predicate_pass=predicate_pass,
        outcome_score=outcome_score, drift=drift,
        divergence=bool(diverged_keys), diverged_keys=diverged_keys,
        displacement=displacement, triggered=triggered,
        recovered_faults=0,   # set below: recovery is a run-level verdict
        untriggered_ids=[e.id for e in injector.untriggered()],
        halted=report.halted, halt_reason=report.halt_reason,
        steps_executed=len(report.completed),
        cost_usd=meter.total_cost(), final_state=final_state)


def clean_reference_state(task: TaskSpec) -> dict:
    """The task's fault-free final state (arm-independent: same worker,
    same tools — the reference every injected run is compared against)."""
    return run_configuration(task, "ungoverned", [], "clean").final_state


# --------------------------------------------------------------------------
# Arm + frontier reports
# --------------------------------------------------------------------------

def _class_key(t: dict) -> str:
    return SUB_TIMING if t.get("subspecies") == SUB_TIMING else t["fault"]


@dataclass
class ArmReport:
    arm: str
    outcomes: list[RunOutcome] = field(default_factory=list)
    repeats_k: int = 1

    def __post_init__(self):
        # Recovery is a run-level verdict (Scout 3 B5): a triggered
        # fault counts recovered iff its run completed AND the final
        # state passed the predicate.
        for o in self.outcomes:
            o.recovered_faults = len(o.triggered) if o.success else 0

    # -- volume ---------------------------------------------------------
    @property
    def runs(self) -> int:
        return len(self.outcomes)

    @property
    def claimed_count(self) -> int:
        return sum(1 for o in self.outcomes if o.claimed_complete)

    @property
    def completion_rate(self) -> float:
        if not self.outcomes:
            return 0.0
        return round(self.claimed_count / len(self.outcomes), 4)

    @property
    def successes(self) -> int:
        return sum(1 for o in self.outcomes if o.success)

    # -- the three named measures (AM-4) --------------------------------
    @property
    def drift_events(self) -> int:
        return sum(1 for o in self.outcomes if o.drift)

    @property
    def drift_per_injected_run(self):
        injected = [o for o in self.outcomes if o.manifest_id != "clean"]
        if not injected:
            return "n/a (no injected runs)"
        return round(self.drift_events / len(injected), 4)

    @property
    def drift_among_unrecovered_value(self):
        exposed = [o for o in self.outcomes if not o.success
                   and any(t["fault"] == FAULT_VALUE for t in o.triggered)]
        if not exposed:
            return "n/a (no unrecovered value faults)"
        drifted = sum(1 for o in exposed if o.drift)
        return round(drifted / len(exposed), 4)

    @property
    def divergence_events(self) -> int:
        return sum(1 for o in self.outcomes if o.divergence)

    @property
    def displacement_events(self) -> int:
        return sum(1 for o in self.outcomes if o.displacement)

    # -- recovery (AM-3 denominators: triggered only; timing separate) --
    def _fault_counts(self, recovered: bool) -> dict[str, int]:
        counts = {FAULT_CRASH: 0, FAULT_OMISSION: 0, FAULT_VALUE: 0,
                  SUB_TIMING: 0}
        for o in self.outcomes:
            for t in o.triggered:
                if recovered and not o.success:
                    continue
                counts[_class_key(t)] += 1
        return counts

    @property
    def triggered_by_class(self) -> dict[str, int]:
        return self._fault_counts(recovered=False)

    @property
    def recovered_by_class(self) -> dict[str, int]:
        return self._fault_counts(recovered=True)

    @property
    def recovery_rate(self):
        """Headline recovery: crash + plain omission + value, pooled.
        Timing is NEVER pooled into this number (AM-3)."""
        trig = self.triggered_by_class
        rec = self.recovered_by_class
        denom = trig[FAULT_CRASH] + trig[FAULT_OMISSION] + trig[FAULT_VALUE]
        if denom == 0:
            return "n/a (no triggered faults)"
        numer = rec[FAULT_CRASH] + rec[FAULT_OMISSION] + rec[FAULT_VALUE]
        return round(numer / denom, 4)

    @property
    def timing_recovery_rate(self):
        trig = self.triggered_by_class[SUB_TIMING]
        if trig == 0:
            return "n/a (no triggered timing faults)"
        return round(self.recovered_by_class[SUB_TIMING] / trig, 4)

    # -- cost (Scout 3 B7: metered, all runs in the numerator) ----------
    @property
    def total_cost_usd(self) -> float:
        return round(sum(o.cost_usd for o in self.outcomes), 6)

    @property
    def cost_per_success(self):
        if self.successes == 0:
            return "n/a (no completions)"
        return round(self.total_cost_usd / self.successes, 6)

    @property
    def wasted_cost_share(self):
        total = sum(o.cost_usd for o in self.outcomes)
        if total == 0:
            return "n/a (no metered spend)"
        wasted = sum(o.cost_usd for o in self.outcomes if not o.success)
        return round(wasted / total, 4)

    # -- pass^k -----------------------------------------------------------
    def _config_successes(self) -> dict[tuple[str, str], list[bool]]:
        configs: dict[tuple[str, str], list[bool]] = {}
        for o in self.outcomes:
            configs.setdefault((o.task_id, o.manifest_id), []).append(o.success)
        return configs

    @property
    def pass1(self) -> float:
        configs = self._config_successes()
        if not configs:
            return 0.0
        # outcomes are appended repeat-major per config; first entry per
        # config is repeat 0 by construction in run_suite.
        return round(sum(1 for v in configs.values() if v[0]) / len(configs), 4)

    @property
    def passk(self) -> float:
        configs = self._config_successes()
        if not configs:
            return 0.0
        return round(sum(1 for v in configs.values() if all(v))
                     / len(configs), 4)

    @property
    def untriggered_entry_ids(self) -> list[str]:
        return sorted({i for o in self.outcomes for i in o.untriggered_ids})

    def to_dict(self) -> dict:
        return {
            "arm": self.arm,
            "runs": self.runs,
            "completion_rate": self.completion_rate,
            "successes": self.successes,
            "drift_events": self.drift_events,
            "drift_per_injected_run": self.drift_per_injected_run,
            "drift_among_unrecovered_value": self.drift_among_unrecovered_value,
            "divergence_events": self.divergence_events,
            "displacement_events": self.displacement_events,
            "triggered_by_class": self.triggered_by_class,
            "recovered_by_class": self.recovered_by_class,
            "recovery_rate": self.recovery_rate,
            "timing_recovery_rate": self.timing_recovery_rate,
            "total_cost_usd": self.total_cost_usd,
            "cost_per_success_usd": self.cost_per_success,
            "wasted_cost_share": self.wasted_cost_share,
            "pass1": self.pass1,
            f"pass{self.repeats_k}": self.passk,
            "untriggered_entry_ids": self.untriggered_entry_ids,
        }


@dataclass
class SuiteBReport:
    arms: dict[str, ArmReport]
    manifest_hash: str
    seed: int
    repeats_k: int
    n_tasks: int
    drift_without_value_fault: int     # Thoth's expander check

    # Legacy headline surface: the governed arm is the suite's subject.
    @property
    def governed(self) -> ArmReport:
        return self.arms["governed"]

    @property
    def outcomes(self) -> list[RunOutcome]:
        return self.governed.outcomes

    @property
    def completion_rate(self) -> float:
        return self.governed.completion_rate

    @property
    def recovery_rate(self):
        return self.governed.recovery_rate

    @property
    def total_drift(self) -> int:
        return self.governed.drift_events

    @property
    def cost_per_success(self):
        return self.governed.cost_per_success

    def to_dict(self) -> dict:
        return {
            "suite": "B-long-horizon-reliability",
            "tasks": self.n_tasks,
            "seed": self.seed,
            "repeats_k": self.repeats_k,
            "manifest_hash": self.manifest_hash,
            "claim": NARROW_CLAIM,
            "arms": {name: arm.to_dict() for name, arm in self.arms.items()},
            "thoth_expander": {
                "check": "drift events whose run triggered no value fault",
                "predicted": 0,
                "observed": self.drift_without_value_fault,
                "holds": self.drift_without_value_fault == 0,
            },
            # Governed-arm headline keys (the suite's subject).
            "completion_rate": self.completion_rate,
            "recovery_rate": self.recovery_rate,
            "drift_events": self.total_drift,
            "cost_per_success_usd": self.cost_per_success,
        }


def run_suite(n_tasks: int = 10, seed: int = DEFAULT_SEED, k: int = 3,
              arms: tuple[str, ...] = ("governed", "ungoverned")
              ) -> SuiteBReport:
    """The full benchmark: every task x (clean + 5 manifests) x arms x
    k repeats, all deterministic. pass^k uses k=3 on this demo
    configuration; because the workers are scripted and deterministic,
    repeats are identical by construction — pass^k here certifies
    reproducibility of the harness, and the report says so by design."""
    tasks = TASKS[:n_tasks]
    manifests, mhash = build_manifest(seed, tasks)
    clean_states = {t.id: clean_reference_state(t) for t in tasks}
    arm_reports: dict[str, ArmReport] = {}
    drift_without_value = 0
    for arm in arms:
        outcomes: list[RunOutcome] = []
        for task in tasks:
            configs: list[tuple[str, list[FaultEntry]]] = [("clean", [])]
            configs += [(mid, manifests[(task.id, mid)])
                        for mid in MANIFEST_IDS]
            for manifest_id, entries in configs:
                for rep in range(k):
                    outcome = run_configuration(
                        task, arm, entries, manifest_id, rep,
                        clean_state=clean_states[task.id])
                    outcomes.append(outcome)
                    if outcome.drift and not any(
                            t["fault"] == FAULT_VALUE
                            for t in outcome.triggered):
                        drift_without_value += 1
        arm_reports[arm] = ArmReport(arm=arm, outcomes=outcomes, repeats_k=k)
    return SuiteBReport(arms=arm_reports, manifest_hash=mhash, seed=seed,
                        repeats_k=k, n_tasks=len(tasks),
                        drift_without_value_fault=drift_without_value)
