"""Weighted-rubric grading.

Every consequential output is scored against a named rubric before it is
accepted. A rubric's weights must sum to 1.0. A missing criterion score is
an error, never a silent zero — grading, like everything in Chancellor,
fails closed.

Finite-value posture (W1): every number that crosses the grading boundary
— criterion scores, rubric weights, max scores, verdict marks — must be
a finite real number. NaN is the dangerous case: it compares False
against every bound, so a NaN score used to slip past the range check and
poison the total, and a NaN weight used to slip past the weight-sum
check. Non-numeric values (strings, bools, None, containers) are refused
too. An invalid number is never graded; it raises.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field


def _require_finite(value: object, what: str) -> float:
    """Coerce a boundary number to float, refusing anything non-finite
    or non-numeric. bool is rejected explicitly: True is not a score."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{what} must be a real number, got {type(value).__name__}")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{what} must be finite, got {out}")
    return out


@dataclass
class Criterion:
    name: str
    weight: float  # 0..1, all weights in a rubric sum to 1.0
    max_score: float = 10.0
    description: str = ""

    def __post_init__(self):
        _validate_criterion(self)


def _validate_criterion(crit: Criterion) -> None:
    """One criterion's boundary checks: finite, non-negative weight;
    finite, positive max_score. Called at construction AND at grade
    time — dataclass fields are mutable, so the boundary re-checks."""
    crit.weight = _require_finite(crit.weight, f"weight of criterion '{crit.name}'")
    if crit.weight < 0:
        raise ValueError(f"weight of criterion '{crit.name}' is negative")
    crit.max_score = _require_finite(
        crit.max_score, f"max_score of criterion '{crit.name}'"
    )
    if crit.max_score <= 0:
        raise ValueError(f"max_score of criterion '{crit.name}' must be positive")


@dataclass
class GradeResult:
    rubric: str
    total: float  # normalized 0..100
    verdict: str  # "pass" | "revise" | "fail"
    per_criterion: dict[str, float] = field(default_factory=dict)


@dataclass
class Rubric:
    name: str
    criteria: list[Criterion]
    pass_mark: float = 70.0  # total >= pass_mark  -> pass
    revise_mark: float = 50.0  # total >= revise_mark -> revise; below -> fail

    def __post_init__(self):
        _validate_rubric(self)


def _validate_rubric(rubric: Rubric) -> None:
    """Full rubric validation. Called at construction AND at grade time:
    dataclass fields are mutable, so a rubric that was valid when built
    can be poisoned afterwards — the boundary re-checks, every time."""
    if not rubric.criteria:
        raise ValueError(f"rubric {rubric.name} has no criteria")
    rubric.pass_mark = _require_finite(
        rubric.pass_mark, f"pass_mark of rubric '{rubric.name}'"
    )
    rubric.revise_mark = _require_finite(
        rubric.revise_mark, f"revise_mark of rubric '{rubric.name}'"
    )
    if not (0.0 <= rubric.revise_mark <= rubric.pass_mark <= 100.0):
        raise ValueError(
            f"rubric {rubric.name} marks out of order: revise_mark="
            f"{rubric.revise_mark}, pass_mark={rubric.pass_mark} (need "
            "0 <= revise <= pass <= 100)"
        )
    total_weight = 0.0
    for crit in rubric.criteria:
        # Re-run the criterion's own validation: fields may have been
        # mutated after construction.
        _validate_criterion(crit)
        total_weight += crit.weight
    if not math.isfinite(total_weight) or abs(total_weight - 1.0) > 1e-6:
        raise ValueError(
            f"rubric {rubric.name} weights sum to {total_weight:.4f}, must be 1.0"
        )
    names = [c.name for c in rubric.criteria]
    if len(set(names)) != len(names):
        raise ValueError(f"rubric {rubric.name} has duplicate criterion names")


def verdict_for(total: float, rubric: Rubric) -> str:
    """The verdict band a total falls in under a rubric's marks — the
    one copy of the band logic; calibration measures band agreement
    against these same bands."""
    if total >= rubric.pass_mark:
        return "pass"
    if total >= rubric.revise_mark:
        return "revise"
    return "fail"


def grade(rubric: Rubric, scores: Mapping[str, float]) -> GradeResult:
    """Score an output. `scores` maps criterion name -> raw score (0..max).

    Fails closed: a missing, non-numeric, non-finite, or out-of-range
    score raises ValueError. Nothing invalid is ever graded.
    """
    _validate_rubric(rubric)
    if not isinstance(scores, Mapping):
        raise ValueError(
            f"scores for rubric '{rubric.name}' must be a mapping of "
            f"criterion -> score, got {type(scores).__name__}"
        )
    per: dict[str, float] = {}
    total = 0.0
    for crit in rubric.criteria:
        if crit.name not in scores:
            raise ValueError(
                f"missing score for criterion '{crit.name}' in rubric '{rubric.name}' "
                "— refusing to grade (fail-closed)"
            )
        raw = _require_finite(scores[crit.name], f"score for criterion '{crit.name}'")
        if raw < 0 or raw > crit.max_score:
            raise ValueError(
                f"score for '{crit.name}' is {raw}, outside 0..{crit.max_score}"
            )
        per[crit.name] = raw
        total += (raw / crit.max_score) * crit.weight * 100.0
    if not math.isfinite(total):  # unreachable once inputs are finite; belt anyway
        raise ValueError(f"grading '{rubric.name}' produced a non-finite total")
    verdict = verdict_for(total, rubric)
    return GradeResult(
        rubric=rubric.name, total=round(total, 2), verdict=verdict, per_criterion=per
    )


# The default rubric for worker outputs in a crew run.
OUTPUT_RUBRIC = Rubric(
    name="worker-output",
    criteria=[
        Criterion("correctness", 0.35, description="Claims and results are right"),
        Criterion("completeness", 0.25, description="Covers everything the task asked"),
        Criterion("clarity", 0.20, description="A reviewer can verify it quickly"),
        Criterion("safety", 0.20, description="No gate violations, no invented facts"),
    ],
)
