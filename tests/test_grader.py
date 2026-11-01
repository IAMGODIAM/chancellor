import pytest

from chancellor.grader import Criterion, Rubric, grade

RUBRIC = Rubric(
    "r", [Criterion("a", 0.6), Criterion("b", 0.4)], pass_mark=70, revise_mark=50
)


def test_weight_sum_enforced():
    with pytest.raises(ValueError):
        Rubric("bad", [Criterion("a", 0.5), Criterion("b", 0.4)])


def test_grade_math_and_verdicts():
    assert grade(RUBRIC, {"a": 10, "b": 10}).total == 100.0
    assert grade(RUBRIC, {"a": 10, "b": 10}).verdict == "pass"
    assert grade(RUBRIC, {"a": 6, "b": 6}).verdict == "revise"
    assert grade(RUBRIC, {"a": 2, "b": 2}).verdict == "fail"


def test_missing_criterion_fails_closed():
    with pytest.raises(ValueError):
        grade(RUBRIC, {"a": 10})


def test_out_of_range_score_rejected():
    with pytest.raises(ValueError):
        grade(RUBRIC, {"a": 11, "b": 5})
