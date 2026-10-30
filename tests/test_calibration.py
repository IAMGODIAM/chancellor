"""Calibration: kappa/rho statistics validated on known-agreement data,
the sealed key's discipline, and the calibration run against a
scripted judge. (The filled key below is TEST SCAFFOLDING with uniform
synthetic values — the shipped template stays empty; see calibration.py.)
"""
import re

import pytest

from chancellor.api_client import ChatResponse, MetaModelClient
from chancellor.evals import calibration as cal
from chancellor.evals.suite_a import NORMATIVE_RUBRIC
from chancellor.evals.suite_a_references import REFERENCES
from chancellor.judge import Judge


# ---- statistics on known-agreement data -------------------------------

def test_weighted_kappa_perfect_agreement_is_one():
    a = [0.0, 3.0, 5.0, 7.0, 10.0, 8.0, 2.0]
    assert cal.weighted_kappa(a, a) == pytest.approx(1.0)


def test_weighted_kappa_symmetric_and_near_miss_is_high():
    a = [1.0, 4.0, 6.0, 9.0, 3.0, 8.0, 5.0, 7.0]
    b = [2.0, 4.0, 5.0, 9.0, 4.0, 7.0, 6.0, 7.0]  # every rating within 1
    assert cal.weighted_kappa(a, b) == pytest.approx(cal.weighted_kappa(b, a))
    assert cal.weighted_kappa(a, b) > 0.8


def test_weighted_kappa_chance_agreement_is_near_zero():
    a = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0] * 3
    b = [5.0, 9.0, 1.0, 7.0, 3.0, 10.0, 0.0, 8.0, 2.0, 6.0, 4.0] * 3
    assert abs(cal.weighted_kappa(a, b)) < 0.3


def test_cohen_kappa_textbook_example():
    # agree 3/4, chance 1/2 -> kappa = 0.5 exactly
    assert cal.cohen_kappa(["p", "p", "f", "f"], ["p", "f", "f", "f"]) == pytest.approx(0.5)
    assert cal.cohen_kappa(["p", "f"], ["p", "f"]) == pytest.approx(1.0)


def test_spearman_monotone_and_reversed():
    a = [10.0, 20.0, 30.0, 40.0]
    assert cal.spearman(a, a) == pytest.approx(1.0)
    assert cal.spearman(a, list(reversed(a))) == pytest.approx(-1.0)
    assert cal.spearman([1.0, 2.0, 2.0, 4.0], [1.0, 2.0, 2.0, 4.0]) == pytest.approx(1.0)


# ---- the sealed key -----------------------------------------------------

SYNTHETIC = {"strong": 8.0, "mediocre": 5.0, "fluent_but_wrong": 3.0}


def filled_test_key():
    """TEST-ONLY filler: uniform synthetic scores so the machinery can be
    exercised. Not a human key and never shipped as one."""
    key = cal.empty_key()
    for (sid, quality), cells in key.items():
        for crit in cells:
            cells[crit] = {"score": SYNTHETIC[quality], "rationale": "test rationale"}
    return key


def test_empty_key_has_36_unscored_entries():
    key = cal.empty_key()
    assert len(key) == 36
    assert all(cell["score"] is None for cells in key.values() for cell in cells.values())
    with pytest.raises(cal.KeyIncompleteError):
        cal.validate_key(key)


def test_filled_key_validates_and_roundtrips_json():
    key = filled_test_key()
    cal.validate_key(key)
    assert cal.key_from_json(cal.key_to_json(key)) == key
    scores = cal.key_scores(key)
    assert scores[("A01", "strong")]["proportionality"] == 8.0


def test_key_with_missing_rationale_is_refused():
    key = filled_test_key()
    key[("A01", "strong")]["proportionality"]["rationale"] = "  "
    with pytest.raises(cal.KeyIncompleteError):
        cal.validate_key(key)


# ---- comparison + the calibration run -----------------------------------

def pairs_from_key(key, mutate=None):
    human = cal.key_scores(key)
    pairs = []
    for ref in REFERENCES:
        b = dict(human[ref.key])
        if mutate:
            b = mutate(ref, b)
        pairs.append(cal.ScorePair(ref.key, human[ref.key], b))
    return pairs


def test_identical_raters_pass_the_gate_with_intervals():
    report = cal.compare_score_sets(pairs_from_key(filled_test_key()))
    assert report["gate"]["passes"] is True
    assert report["mae_totals"] == 0.0
    for d in report["per_criterion_weighted_kappa"].values():
        assert d["value"] == pytest.approx(1.0)
        assert d["ci95"][0] <= d["value"] <= d["ci95"][1]
        assert d["n"] == 36


def test_divergent_rater_fails_the_gate():
    def drag_down(ref, scores):
        if ref.quality == "fluent_but_wrong":  # a style-captured judge
            return {k: 9.0 for k in scores}
        return scores
    report = cal.compare_score_sets(pairs_from_key(filled_test_key(), drag_down))
    assert report["gate"]["passes"] is False
    assert report["mae_totals"] > 0


def test_run_calibration_against_scripted_judge():
    key = filled_test_key()
    human = cal.key_scores(key)
    by_text = {ref.text: human[ref.key] for ref in REFERENCES}

    def transport(model, messages, **kw):
        user = messages[-1].content
        crit = re.search(r"Criterion: (\w+)", user).group(1)
        for text, scores in by_text.items():
            if text in user:
                return ChatResponse(text=f"Matches the key.\nSCORE: {scores[crit]}",
                                    model=model)
        raise AssertionError("proposal not found in judge prompt")

    judge = Judge(MetaModelClient(transport=transport), model="muse-wonder-1.0",
                  rubric=NORMATIVE_RUBRIC, worker_model="muse-spark-1.3")
    report = cal.run_calibration(judge, key)
    assert report["judge_pin"] == judge.pin
    assert report["references"] == 36
    assert report["gate"]["passes"] is True


def test_run_calibration_refuses_incomplete_key():
    judge = Judge(MetaModelClient(transport=lambda m, msgs, **k: None),
                  model="muse-wonder-1.0", rubric=NORMATIVE_RUBRIC)
    with pytest.raises(cal.KeyIncompleteError):
        cal.run_calibration(judge, cal.empty_key())
