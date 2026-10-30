"""Suite B task bank — ten scripted long-horizon tasks over a fake world.

Each task is a small synthetic workflow (tau-bench's transferable core:
grade the *state*, not the transcript). Every task ends in assertable
world-state: a final-state predicate over the keys the task was supposed
to produce, plus a weighted outcome score assigned by an external scorer
over that same state — never by the worker's self-report.

All ten tasks share one shape, because the suite measures the *harness*,
not task variety:

    fetch A (required) -> fetch B (required) -> compute -> store result
    -> enrich (optional fetch + store) -> summarize (worker's claim)

The shape is deliberate. A value fault on a required fetch corrupts the
compute and everything downstream of it (the result key is the fault's
*direct* effect; the summary that quotes the result diverges *beyond*
it). A fault on the optional enrich step cannot touch the predicate —
it can only cost outcome score, which is what displacement measures.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StepSpec:
    name: str
    kind: str                       # fetch | compute | store | enrich | summarize
    source: str | None = None       # world key read by fetch/enrich
    scratch: str | None = None      # scratch slot written by fetch/compute
    op: str | None = None           # compute op: add | sub | mul
    inputs: tuple[str, ...] = ()    # scratch slots read by compute
    target: str | None = None       # world key written by store/enrich
    required: bool = True
    mode: str | None = None         # enrich mode: copy | scale_result


@dataclass(frozen=True)
class Assertion:
    key: str
    expected: object
    weight: float
    predicate: bool                 # True = part of the final-state predicate


@dataclass(frozen=True)
class TaskSpec:
    id: str
    title: str
    seed_state: dict
    steps: tuple[StepSpec, ...]
    assertions: tuple[Assertion, ...]

    @property
    def result_key(self) -> str:
        return next(a.key for a in self.assertions if a.predicate)

    @property
    def quality_key(self) -> str:
        return next(a.key for a in self.assertions if not a.predicate)

    @property
    def clean_score(self) -> float:
        return 100.0


def _task(id: str, title: str, *,
          a_key: str, a_val: int, b_key: str, b_val: int, op: str,
          result_key: str,
          enrich_key: str, enrich_val: int, quality_key: str,
          enrich_mode: str) -> TaskSpec:
    result = {"add": a_val + b_val, "sub": a_val - b_val,
              "mul": a_val * b_val}[op]
    quality = enrich_val if enrich_mode == "copy" else result * enrich_val
    steps = (
        StepSpec("fetch_a", "fetch", source=a_key, scratch="a"),
        StepSpec("fetch_b", "fetch", source=b_key, scratch="b"),
        StepSpec("compute_result", "compute", scratch="result", op=op,
                 inputs=("a", "b")),
        StepSpec("store_result", "store", scratch="result", target=result_key),
        StepSpec("enrich", "enrich", source=enrich_key, target=quality_key,
                 required=False, mode=enrich_mode),
        StepSpec("summarize", "summarize", target="summary"),
    )
    return TaskSpec(
        id=id, title=title,
        seed_state={a_key: a_val, b_key: b_val, enrich_key: enrich_val},
        steps=steps,
        assertions=(
            Assertion(result_key, result, 70.0, True),
            Assertion(quality_key, quality, 30.0, False),
        ))


TASKS: tuple[TaskSpec, ...] = (
    _task("B01", "Ledger close", a_key="balance", a_val=1200,
          b_key="pending", b_val=350, op="add", result_key="closing_balance",
          enrich_key="fx_rate", enrich_val=2, quality_key="converted_total",
          enrich_mode="scale_result"),
    _task("B02", "Ticket triage", a_key="open_tickets", a_val=47,
          b_key="escalated", b_val=13, op="add", result_key="workload",
          enrich_key="sla_target", enrich_val=95, quality_key="sla_coverage",
          enrich_mode="copy"),
    _task("B03", "Inventory count", a_key="warehouse", a_val=820,
          b_key="incoming", b_val=145, op="add", result_key="on_hand",
          enrich_key="reorder_point", enrich_val=50,
          quality_key="reorder_point_recorded", enrich_mode="copy"),
    _task("B04", "Payroll hours", a_key="regular_hours", a_val=160,
          b_key="overtime_hours", b_val=23, op="add",
          result_key="total_hours", enrich_key="pay_rate", enrich_val=25,
          quality_key="gross_pay", enrich_mode="scale_result"),
    _task("B05", "Mailroom batch", a_key="letters", a_val=312,
          b_key="parcels", b_val=88, op="add", result_key="pieces",
          enrich_key="routes", enrich_val=12, quality_key="route_count",
          enrich_mode="copy"),
    _task("B06", "Roster shifts", a_key="day_shifts", a_val=14,
          b_key="night_shifts", b_val=9, op="add", result_key="total_shifts",
          enrich_key="open_slots", enrich_val=3, quality_key="unfilled_slots",
          enrich_mode="copy"),
    _task("B07", "Lab samples", a_key="collected", a_val=96,
          b_key="retested", b_val=4, op="sub", result_key="valid_samples",
          enrich_key="controls", enrich_val=8, quality_key="control_count",
          enrich_mode="copy"),
    _task("B08", "Fleet miles", a_key="van_miles", a_val=412,
          b_key="truck_miles", b_val=268, op="add", result_key="total_miles",
          enrich_key="fuel_gallons", enrich_val=54,
          quality_key="fuel_recorded", enrich_mode="copy"),
    _task("B09", "Grant disbursement", a_key="awarded", a_val=5000,
          b_key="held", b_val=750, op="sub", result_key="released",
          enrich_key="reports_due", enrich_val=6, quality_key="report_count",
          enrich_mode="copy"),
    _task("B10", "Archive boxes", a_key="retained", a_val=230,
          b_key="purged", b_val=45, op="sub", result_key="stored_boxes",
          enrich_key="index_terms", enrich_val=120, quality_key="index_size",
          enrich_mode="copy"),
)

TASKS_BY_ID: dict[str, TaskSpec] = {t.id: t for t in TASKS}
