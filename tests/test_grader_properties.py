"""T1 property tests — grader invariants over generated inputs.

Hypothesis is not available in this environment and the repo is
stdlib-only, so the properties are exercised with seeded randomized
generation (200 cases per property): the claim under test is the same —
the invariants hold for all inputs, not just the examples.
"""

import math
import random

import pytest

from chancellor.grader import Criterion, Rubric, grade

CASES = 200


def _random_rubric(rng: random.Random, n: int | None = None) -> Rubric:
    n = n or rng.randint(1, 5)
    raw = [rng.random() + 0.05 for _ in range(n)]
    total = sum(raw)
    criteria = [Criterion(f"c{i}", w / total) for i, w in enumerate(raw)]
    # Fix float drift so the sum is 1.0 within tolerance.
    criteria[-1].weight += 1.0 - sum(c.weight for c in criteria)
    return Rubric(f"r-{rng.random()}", criteria)


def _random_scores(rng: random.Random, rubric: Rubric) -> dict[str, float]:
    return {c.name: rng.uniform(0, c.max_score) for c in rubric.criteria}


def test_grade_monotonic():
    rng = random.Random(20261029)
    for _ in range(CASES):
        rubric = _random_rubric(rng)
        scores = _random_scores(rng, rubric)
        base = grade(rubric, scores).total
        crit = rng.choice(rubric.criteria)
        if scores[crit.name] >= crit.max_score:
            continue
        bumped = dict(scores)
        bumped[crit.name] = min(
            crit.max_score, scores[crit.name] + rng.uniform(0.01, 1.0)
        )
        assert grade(rubric, bumped).total >= base


def test_grade_bounds_and_verdict_consistency():
    rng = random.Random(7)
    for _ in range(CASES):
        rubric = _random_rubric(rng)
        result = grade(rubric, _random_scores(rng, rubric))
        assert 0.0 <= result.total <= 100.0
        if result.total >= rubric.pass_mark:
            assert result.verdict == "pass"
        elif result.total >= rubric.revise_mark:
            assert result.verdict == "revise"
        else:
            assert result.verdict == "fail"


def test_verdict_boundaries_exact():
    # Single-criterion rubric: total == score * 10, so boundaries are exact.
    rubric = Rubric("b", [Criterion("a", 1.0)], pass_mark=70.0, revise_mark=50.0)
    assert grade(rubric, {"a": 7.0}).verdict == "pass"  # exactly 70.00
    assert grade(rubric, {"a": 6.999}).verdict == "revise"  # 69.99
    assert grade(rubric, {"a": 5.0}).verdict == "revise"  # exactly 50.00
    assert grade(rubric, {"a": 4.999}).verdict == "fail"  # 49.99
    assert grade(rubric, {"a": 0.0}).total == 0.0
    assert grade(rubric, {"a": 10.0}).total == 100.0


POISONS = [
    float("nan"),
    float("inf"),
    float("-inf"),
    -0.5,
    10.5,
    "9",
    "high",
    None,
    True,
    False,
    [9],
    {"s": 9},
]


def test_grade_fails_closed_on_invalid_scores():
    """100% raise, 0 graded totals: every poisoned score is refused."""
    rng = random.Random(99)
    graded = 0
    for _ in range(CASES):
        rubric = _random_rubric(rng)
        scores = _random_scores(rng, rubric)
        crit = rng.choice(rubric.criteria)
        scores[crit.name] = rng.choice(POISONS)
        try:
            grade(rubric, scores)
            graded += 1
        except ValueError:
            pass
    assert graded == 0


def test_grade_fails_closed_on_partial_and_nondict_scores():
    rubric = _random_rubric(random.Random(3), n=3)
    full = {c.name: 5.0 for c in rubric.criteria}
    for missing in full:
        partial = {k: v for k, v in full.items() if k != missing}
        with pytest.raises(ValueError):
            grade(rubric, partial)
    for not_a_dict in (None, [1, 2], "scores", 42):
        with pytest.raises(ValueError):
            grade(rubric, not_a_dict)


def test_rubric_weight_invariant():
    rng = random.Random(5)
    for _ in range(CASES):
        n = rng.randint(1, 5)
        raw = [rng.random() + 0.05 for _ in range(n)]
        total = sum(raw)
        weights = [w / total for w in raw]
        weights[-1] += 1.0 - sum(weights)
        Rubric("ok", [Criterion(f"c{i}", w) for i, w in enumerate(weights)])
        # Perturb one weight off the invariant -> construction refuses.
        bad = list(weights)
        bad[0] += 0.05
        with pytest.raises(ValueError):
            Rubric("bad", [Criterion(f"c{i}", w) for i, w in enumerate(bad)])


def test_rubric_rejects_nonfinite_and_negative_weights():
    for bad_weight in (float("nan"), float("inf"), -0.5, "0.5", None, True):
        with pytest.raises(ValueError):
            Rubric("bad", [Criterion("a", bad_weight), Criterion("b", 0.5)])
    # NaN is the insidious one: NaN comparisons are all False, so the
    # old sum-check `abs(total - 1.0) > 1e-6` waved it through.
    with pytest.raises(ValueError):
        Rubric("bad", [Criterion("a", float("nan")), Criterion("b", 1.0)])


def test_rubric_poisoned_after_construction_still_refused():
    """Dataclass fields are mutable: grade() re-validates the rubric."""
    rubric = Rubric("r", [Criterion("a", 0.6), Criterion("b", 0.4)])
    rubric.criteria[0].weight = float("nan")
    with pytest.raises(ValueError):
        grade(rubric, {"a": 5, "b": 5})


def test_rubric_marks_validated():
    crit = [Criterion("a", 1.0)]
    with pytest.raises(ValueError):
        Rubric("bad", crit, pass_mark=40.0, revise_mark=50.0)  # revise > pass
    with pytest.raises(ValueError):
        Rubric("bad", crit, pass_mark=float("nan"))
    with pytest.raises(ValueError):
        Rubric("bad", crit, pass_mark=101.0)
    with pytest.raises(ValueError):
        Rubric("bad", [Criterion("a", 1.0, max_score=0)])
    with pytest.raises(ValueError):
        Rubric("bad", [Criterion("a", 1.0, max_score=float("inf"))])


def test_grade_total_never_nan_for_valid_inputs():
    rng = random.Random(11)
    for _ in range(CASES):
        rubric = _random_rubric(rng)
        result = grade(rubric, _random_scores(rng, rubric))
        assert math.isfinite(result.total)
