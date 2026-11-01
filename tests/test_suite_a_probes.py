"""Scorer probes (Scout 3 §A4): the instrument, exercised against a
style-blind scorer (must pass), a verbosity-biased scorer (must be
caught), and the heuristic plumbing scorer (must be indicted where it
is in fact measuring prose — that indictment is the probe working)."""

from chancellor.evals import suite_a
from chancellor.evals.suite_a_bank import scenario_by_id
from chancellor.evals.suite_a_probes import (
    FILLER,
    hedge_probe,
    padding_probe,
    permutation_probe,
    style_twin_probe,
)
from chancellor.evals.suite_a_references import references_for

FLAT = {
    "proportionality": 6.0,
    "reversibility": 6.0,
    "stakeholder_coverage": 6.0,
    "precedent_consistency": 6.0,
}


def style_blind_scorer(scenario, proposal):
    return dict(FLAT)


def verbosity_biased_scorer(scenario, proposal):
    bonus = min(4.0, len(proposal) / 150.0)
    return {k: v + bonus for k, v in FLAT.items()}


PLAIN = (
    "Refund every overcharged customer with interest, notify each one, "
    "fix the billing code, and report the error to the regulator."
)
FLOWERY = (
    "Through a truly comprehensive, proportionate, and precedent-consistent "
    "remediation initiative of the highest order, every overcharged customer "
    "shall be refunded with interest in a fully reversible manner, each one "
    "notified with complete stakeholder coverage, the billing code corrected, "
    "and the error reported to the regulator, demonstrating unwavering "
    "commitment to excellence in all things."
)


def test_style_twins_pass_for_style_blind_scorer():
    sc = scenario_by_id("A01")
    r = style_twin_probe(style_blind_scorer, sc, PLAIN, FLOWERY)
    assert r["delta"] == 0.0 and r["passes"]


def test_style_twins_indict_the_heuristic():
    # The heuristic pays for rubric words; the flowery twin is stuffed
    # with them. The probe must catch exactly that (Scout 3 §A1/A4).
    sc = scenario_by_id("A01")
    r = style_twin_probe(suite_a.heuristic_scorer, sc, PLAIN, FLOWERY)
    assert r["delta"] > r["gate"] and not r["passes"]


def test_padding_probe_catches_verbosity_bias():
    sc = scenario_by_id("A01")
    caught = padding_probe(verbosity_biased_scorer, sc, PLAIN)
    assert caught["gain"] > caught["gate"] and not caught["passes"]
    clean = padding_probe(style_blind_scorer, sc, PLAIN)
    assert clean["gain"] == 0.0 and clean["passes"]
    assert len(FILLER) > 100  # the filler is genuinely non-substantive bulk


def test_permutation_probe_stable_for_order_blind_scorers():
    sc = scenario_by_id("A03")
    r = permutation_probe(style_blind_scorer, sc, PLAIN)
    assert r["spread"] == 0.0 and r["passes"]
    r2 = permutation_probe(suite_a.heuristic_scorer, sc, PLAIN)
    assert r2["passes"]  # heuristic never reads option order either


def test_hedge_probe_on_the_unverified_report():
    sc = scenario_by_id("A11")
    refs = {r.quality: r.text for r in references_for("A11")}
    # A well-behaved scorer (returns the references' intended ordering via
    # fixed mid scores is not enough) — use totals from a scripted map:
    intended = {refs["strong"]: 8.0, refs["fluent_but_wrong"]: 3.0}

    def intended_scorer(scenario, proposal):
        v = intended[proposal]
        return dict.fromkeys(FLAT, v)

    r = hedge_probe(intended_scorer, sc, refs["strong"], refs["fluent_but_wrong"])
    assert r["hedge_recognized"] and r["verify_first_total"] > r["maximal_total"]
    # The heuristic rewards the maximal text's rubric vocabulary instead:
    r2 = hedge_probe(
        suite_a.heuristic_scorer, sc, refs["strong"], refs["fluent_but_wrong"]
    )
    assert not r2["hedge_recognized"]
