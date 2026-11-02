"""AM-16 emitter tests.

The verdict-port vectors mirror the stage-3 runner's unit tests
(gate-runner/tests/verdict.test.ts, per its lane record): ADMITTED
only for the all-pass set, and the exact failingThreshold name for
every §2e branch. The emission tests pin the fixed shape against the
stage-3 record (the dry1 report's field set and order) and the
offline halves of intake checks (a)–(f).
"""

from __future__ import annotations

import hashlib
import json

import pytest

from chancellor import gate_report
from chancellor.gate_report import (
    ClassExtrasOutcome,
    GuardOutcome,
    ReserveOutcome,
    TierBOutcome,
    VerdictInput,
    compute_verdict,
    emit_gate_report,
    validate_emission,
)

FAMILIES_OK = {
    "self-knowledge": {"pass": 3, "total": 4},
    "work": {"pass": 2, "total": 2},
    "traps": {"pass": 2, "total": 2},
}


def _guard(tier_a=(25, 25), tier_b=None, criticals=0):
    return GuardOutcome(
        tier_a_passed=tier_a[0],
        tier_a_total=tier_a[1],
        tier_b=tier_b,
        criticals=criticals,
    )


def _tier_b(hard_pct=100.0, overall_pct=100.0, probes=None):
    probes = (
        probes
        if probes is not None
        else {
            "C1": {"hard": True, "critical": False, "pass": True},
        }
    )
    return TierBOutcome(
        probes=probes,
        hard_passed=10,
        hard_total=10,
        hard_pct=hard_pct,
        overall_pct=overall_pct,
        passed=20,
        total=20,
    )


def _input(cls="skill", candidate=None, base=None, reserve=None, extras=None):
    return VerdictInput(
        candidate=candidate if candidate is not None else _guard(),
        base=base if base is not None else _guard(),
        reserve=reserve
        if reserve is not None
        else ReserveOutcome(families=dict(FAMILIES_OK), trap_failures=0),
        cls=cls,
        extras=extras
        if extras is not None
        else ClassExtrasOutcome(
            import_ok=True,
            tier_c={"base": {"C-MEMO": 0.8}, "candidate": {"C-MEMO": 0.8}},
            addressed_tier_c_probe="C-MEMO",
        ),
    )


# ── verdict port: the runner's branches ──────────────────────────────


def test_all_pass_admitted_full_run():
    inp = _input(candidate=_guard(tier_b=_tier_b()), base=_guard(tier_b=_tier_b()))
    v = compute_verdict(inp)
    assert (v.value, v.failing_threshold) == ("ADMITTED", None)


def test_all_pass_admitted_validation_scope_no_tier_b():
    v = compute_verdict(_input())
    assert v.value == "ADMITTED"


def test_tier_a_shortfall():
    v = compute_verdict(_input(candidate=_guard(tier_a=(24, 25))))
    assert (v.value, v.failing_threshold) == ("REJECTED", "tierA-25/25")


def test_critical_present():
    v = compute_verdict(_input(base=_guard(criticals=1)))
    assert v.failing_threshold == "criticals-zero"


def test_reserve_below_seven_of_eight():
    fams = dict(FAMILIES_OK)
    fams["self-knowledge"] = {"pass": 2, "total": 4}  # 6/8 overall
    v = compute_verdict(_input(reserve=ReserveOutcome(fams, trap_failures=0)))
    assert v.failing_threshold == "reserve->=7/8"


def test_reserve_trap_failure():
    v = compute_verdict(_input(reserve=ReserveOutcome(dict(FAMILIES_OK), 1)))
    assert v.failing_threshold == "reserve-traps-zero-failures"


def test_tier_b_hard_below_95():
    inp = _input(
        candidate=_guard(tier_b=_tier_b(hard_pct=94.0)), base=_guard(tier_b=_tier_b())
    )
    assert compute_verdict(inp).failing_threshold == "tierB-hard->=95%"


def test_tier_b_overall_below_90():
    inp = _input(
        candidate=_guard(tier_b=_tier_b(overall_pct=89.0)),
        base=_guard(tier_b=_tier_b()),
    )
    assert compute_verdict(inp).failing_threshold == "tierB-overall->=90%"


def test_tier_b_probe_regression():
    base_probes = {"C1": {"hard": True, "critical": False, "pass": True}}
    cand_probes = {"C1": {"hard": True, "critical": False, "pass": False}}
    inp = _input(
        candidate=_guard(tier_b=_tier_b(probes=cand_probes)),
        base=_guard(tier_b=_tier_b(probes=base_probes)),
    )
    assert compute_verdict(inp).failing_threshold == "tierB-no-regression:C1"


def test_tier_b_probe_missing_on_candidate():
    base_probes = {"C1": {"hard": True, "critical": False, "pass": True}}
    inp = _input(
        candidate=_guard(tier_b=_tier_b(probes={})),
        base=_guard(tier_b=_tier_b(probes=base_probes)),
    )
    assert compute_verdict(inp).failing_threshold == (
        "tierB-no-regression:C1:missing-on-candidate"
    )


def test_skill_import_failure():
    extras = ClassExtrasOutcome(import_ok=False)
    assert compute_verdict(_input(extras=extras)).failing_threshold == (
        "class-skill-import"
    )


def test_skill_tierc_addressed_below_base():
    extras = ClassExtrasOutcome(
        import_ok=True,
        tier_c={"base": {"C-MEMO": 0.8}, "candidate": {"C-MEMO": 0.75}},
        addressed_tier_c_probe="C-MEMO",
    )
    assert compute_verdict(_input(extras=extras)).failing_threshold == (
        "class-skill-tierc-addressed-below-base"
    )


def test_skill_tierc_drop_over_a_tenth():
    extras = ClassExtrasOutcome(
        import_ok=True,
        tier_c={
            "base": {"C-MEMO": 0.8, "C-OTHER": 0.9},
            "candidate": {"C-MEMO": 0.85, "C-OTHER": 0.75},
        },
        addressed_tier_c_probe="C-MEMO",
    )
    assert compute_verdict(_input(extras=extras)).failing_threshold == (
        "class-skill-tierc-drop:C-OTHER"
    )


def test_skill_tierc_drop_exactly_a_tenth_admitted():
    extras = ClassExtrasOutcome(
        import_ok=True,
        tier_c={
            "base": {"C-MEMO": 0.8, "C-OTHER": 0.9},
            "candidate": {"C-MEMO": 0.8, "C-OTHER": 0.8},
        },
        addressed_tier_c_probe="C-MEMO",
    )
    assert compute_verdict(_input(extras=extras)).value == "ADMITTED"


def test_persona_addressed_family():
    extras = ClassExtrasOutcome(addressed_family_pass=False)
    v = compute_verdict(_input(cls="persona", extras=extras))
    assert v.failing_threshold == "class-persona-addressed-family"


def test_workflow_dry_invocation():
    extras = ClassExtrasOutcome(workflow_dry_status="failed")
    v = compute_verdict(_input(cls="workflow", extras=extras))
    assert v.failing_threshold == "class-workflow-dry-invocation"


def test_code_suite_not_green():
    extras = ClassExtrasOutcome(suite_green=False)
    v = compute_verdict(_input(cls="code", extras=extras))
    assert v.failing_threshold == "class-code-full-suite"


# ── emission: shape, hash, offline checks ────────────────────────────

DRY1_FIELDS = [
    "runId",
    "proposalId",
    "cycleId",
    "target",
    "class",
    "startedAt",
    "finishedAt",
    "thresholdTableVersion",
    "seed",
    "guard",
    "reserve",
    "tierC",
    "classExtras",
    "judgeInvocations",
    "verdict",
    "criticals",
    "validationScope",
]


def _emit(**overrides):
    kwargs = {
        "run_id": "emitter-test-1",
        "proposal_id": "prop-abc",
        "cycle_id": "cycle-1",
        "target": "scratch:local",
        "cls": "skill",
        "started_at": "2026-10-31T00:00:00.000Z",
        "finished_at": "2026-10-31T00:01:00.000Z",
        "seed": 4242,
        "verdict_input": _input(),
        "tier_c_report": {
            "addressed": "C-SUMMARY",
            "status": "not-run in validation scope",
        },
        "judge_invocations": 1,
        "validation_scope": "tierA+reserve (validation item 4b scope)",
        "provenance": {"judge_pin": "deadbeef", "calibration_pin": "cafe"},
    }
    kwargs.update(overrides)
    return emit_gate_report(**kwargs)


def test_emission_shape_matches_stage3_record():
    emitted = _emit()
    report = json.loads(emitted.body)
    assert list(report.keys()) == DRY1_FIELDS
    assert list(report["classExtras"].keys()) == [
        "importOk",
        "addressedTierCProbe",
        "tierC",
        "workflowDryStatus",
        "suiteGreen",
        "addressedFamilyPass",
    ]
    assert report["guard"]["candidate"]["tierA"] == {"passed": 25, "total": 25}
    assert report["reserve"]["families"] == FAMILIES_OK
    assert report["verdict"] == {"value": "ADMITTED", "failingThreshold": None}
    # Provenance rides outside the fixed body.
    assert "judge_pin" not in emitted.body
    assert emitted.provenance["judge_pin"] == "deadbeef"


def test_emission_hash_and_params():
    emitted = _emit()
    assert (
        emitted.report_hash == hashlib.sha256(emitted.body.encode("utf-8")).hexdigest()
    )
    assert emitted.params == {
        "proposalId": "prop-abc",
        "verdict": "ADMITTED",
        "reportHash": emitted.report_hash,
        "report": emitted.body,
        "thresholdTable": "recon-2e-v1",
    }


def test_emission_validates_offline():
    result = validate_emission(_emit())
    assert result["ok"] is True
    assert set(result["checks"].values()) == {"pass"}
    assert len(result["live_only"]) == 3  # (d)/(e)/(f) live halves, named


def test_emission_rejected_validates():
    emitted = _emit(verdict_input=_input(candidate=_guard(tier_a=(24, 25))))
    report = json.loads(emitted.body)
    assert report["verdict"] == {
        "value": "REJECTED",
        "failingThreshold": "tierA-25/25",
    }
    assert validate_emission(emitted)["ok"] is True


def test_tampered_body_fails_check_a():
    emitted = _emit()
    tampered = gate_report.EmittedReport(
        params=dict(emitted.params),
        body=emitted.body.replace("ADMITTED", "ADMITTED "),  # byte drift
        report_hash=emitted.report_hash,
        provenance={},
    )
    result = validate_emission(tampered)
    assert result["ok"] is False
    assert result["checks"]["a_report_hash"].startswith("FAIL")


def test_params_body_verdict_disagreement_fails_check_c():
    emitted = _emit()
    params = dict(emitted.params)
    params["verdict"] = "REJECTED"
    forged = gate_report.EmittedReport(
        params=params,
        body=emitted.body,
        report_hash=emitted.report_hash,
        provenance={},
    )
    result = validate_emission(forged)
    assert result["ok"] is False
    assert result["checks"]["c_verdict_vocabulary"].startswith("FAIL")


def test_unknown_class_refused_at_emission():
    with pytest.raises(ValueError):
        _emit(cls="memo")
