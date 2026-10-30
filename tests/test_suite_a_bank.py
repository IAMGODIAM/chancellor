"""Suite A bank: construction rules (Scout 3 §A2/A3/A5), the gold seal,
twins, and the calibration reference set's shape."""
import re
from collections import Counter

import pytest

from chancellor.api_client import ChatResponse, MetaModelClient
from chancellor.evals import suite_a
from chancellor.evals.suite_a_bank import (
    BANNED_RUBRIC_TERMS, SCENARIOS, TWINS, scenario_by_id, scenario_text)
from chancellor.evals.suite_a_gold import HELD_BACK, gold_stakeholders
from chancellor.evals.suite_a_references import QUALITIES, REFERENCES, references_for
from chancellor.judge import Judge


def test_bank_is_twelve_in_three_tiers():
    assert len(SCENARIOS) == 12
    tiers = Counter(sc.tier for sc in SCENARIOS)
    assert tiers == {"clear": 4, "tradeoff": 5, "trap": 3}
    ids = {sc.id for sc in SCENARIOS}
    assert {f"A{i:02d}" for i in range(1, 13)} == ids


def test_rubric_vocabulary_banned_from_scenario_text():
    for sc in SCENARIOS + TWINS:
        text = scenario_text(sc).lower()
        for term in BANNED_RUBRIC_TERMS:
            assert term not in text, f"{sc.id} leaks rubric term {term!r}"


def test_additions_cover_the_six_named_gaps():
    # A07 unjust line-breaking, A08 remedy-that-kills, A09 victims decline,
    # A10 scarcity, A11 unverified, A12 shared causation (Scout 3 §A5).
    titles = {sc.id: sc.title for sc in SCENARIOS}
    assert titles["A08"] == "The only clinic"
    assert titles["A09"] == "The declined vindication"
    assert titles["A10"] == "One fund, two harms"
    assert titles["A11"] == "The unconfirmed report"
    assert titles["A12"] == "Two hands on the wheel"


def test_gold_lists_exist_and_held_back_names_stay_hidden():
    for sc in SCENARIOS + TWINS:
        gold = gold_stakeholders(sc)
        assert set(sc.stakeholders) < set(gold)  # strictly more than printed
        assert HELD_BACK[sc.id], f"{sc.id} holds nobody back"
        visible = scenario_text(sc).lower()
        for name in HELD_BACK[sc.id]:
            assert name.lower() not in visible, \
                f"{sc.id}: held-back party {name!r} leaks into responder-visible text"


def test_twins_flip_exactly_one_fact():
    assert len(TWINS) >= 2
    for twin in TWINS:
        core = scenario_by_id(twin.twin_of)
        assert twin.options == core.options
        assert twin.stakeholders == core.stakeholders
        assert twin.harm != core.harm and twin.flip


def test_reference_set_is_36_three_per_scenario():
    assert len(REFERENCES) == 36
    for sc in SCENARIOS:
        refs = references_for(sc.id)
        assert len(refs) == 3
        assert {r.quality for r in refs} == set(QUALITIES)
        assert all(len(r.text) > 200 for r in refs)


def test_heuristic_scorer_is_labeled_never_reportable():
    assert suite_a.HEURISTIC_SCORER_REPORTABLE is False
    # Stranger test S1: the label must reach the report a reader sees
    # (the eval-a JSON), not only live in a source constant.
    d = suite_a.run_suite().to_dict()
    assert "NOT REPORTABLE" in d["scorer"]
    assert "heuristic-stub" in d["scorer"]


def test_run_suite_reports_per_tier():
    report = suite_a.run_suite()
    d = report.to_dict()
    assert set(d["tier_means"]) == {"clear", "tradeoff", "trap"}
    assert all(r.tier for r in report.results)


def test_judge_scorer_adapter_grades_through_the_judge():
    # Scripted judge transport: parses the proposal's quality markers to
    # return fixed per-criterion scores; proves the adapter wiring and
    # that coverage context (gold) reaches the judge prompt.
    seen_prompts = []

    def transport(model, messages, **kw):
        user = messages[-1].content
        seen_prompts.append(user)
        crit = re.search(r"Criterion: (\w+)", user).group(1)
        score = {"proportionality": 8.0, "reversibility": 7.0,
                 "stakeholder_coverage": 6.0, "precedent_consistency": 7.0}[crit]
        return ChatResponse(text=f"Reasoned.\nSCORE: {score}", model=model)

    judge = Judge(MetaModelClient(transport=transport), model="muse-wonder-1.0",
                  rubric=suite_a.NORMATIVE_RUBRIC,
                  exemplars=suite_a.NORMATIVE_EXEMPLARS,
                  worker_model="muse-spark-1.3")
    scorer = suite_a.judge_scorer(judge)
    sc = scenario_by_id("A01")
    scores = scorer(sc, "A remedy text.")
    assert set(scores) == {c.name for c in suite_a.NORMATIVE_RUBRIC.criteria}
    coverage_prompts = [p for p in seen_prompts if "stakeholder_coverage" in p]
    assert coverage_prompts and "other billing plans" in coverage_prompts[0]
