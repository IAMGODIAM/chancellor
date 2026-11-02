"""Governed capability install (frame v2, clause 6): the arc, the
refusal register, the budget fold, probation arithmetic, and the
bridge audit — driven against a fake manager gateway so the
Chancellor side is measured on its own. The hearing against the
real Foundry manager is the pre-registered evidence run filed at
docs/evidence/foundry-install-hearing/."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chancellor import installs, receipts
from chancellor.escalation import (
    REFUSAL_APPROVER_DECLINED,
    REFUSAL_INSTALL_BUDGET_EXHAUSTED,
    REFUSAL_INSTALL_COST_REFUSED,
    REFUSAL_INSTALL_INCOMPATIBLE,
    REFUSAL_INSTALL_OUT_OF_SCOPE,
    REFUSAL_INSTALL_PAYLOAD_ESCAPE,
    REFUSAL_INSTALL_PIN_MISMATCH,
    REFUSAL_INSTALL_SNAPSHOT_FAILED,
    REFUSAL_INSTALL_UNCONSENTED_BUILD,
    REFUSAL_INSTALL_UNLICENSED,
    REFUSAL_NO_APPROVER,
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
    Gatekeeper,
)
from chancellor.installs import (
    BundleProposal,
    Commission,
    InstallGovernor,
    PreflightOutcome,
    count_consecutive_failed_attempts,
)
from chancellor.supervise import rebuild_supervision_state
from chancellor.verify_log import audit_install_bridge, verify_log

PIN = "sha256:" + "a" * 64
PIN_B = "sha256:" + "b" * 64
COMMISSION_ID = "c" * 64


class FakeGateway:
    """The manager seam, faked: configurable pre-flight outcomes,
    act results, census pins; records every call."""

    def __init__(self) -> None:
        self.preflight_outcomes: dict[str, PreflightOutcome] = {}
        self.calls: list[tuple] = []
        self.census_pins: dict[str, str | None] = {}
        self.disabled: list[str] = []
        self._act_counter = 0

    def preflight(self, proposal: BundleProposal, verb: str) -> PreflightOutcome:
        self.calls.append(("preflight", proposal.bundle_id, verb))
        if proposal.bundle_id in self.preflight_outcomes:
            return self.preflight_outcomes[proposal.bundle_id]
        return PreflightOutcome(
            ok=True,
            bundle_id=proposal.bundle_id,
            verb=verb,
            record={
                "verdict": "PASS",
                "pin": proposal.manifest_pin,
                "novelty_diff": {
                    "capability_classes_novel": list(proposal.provides),
                    "data_classes_novel": [],
                    "external_surfaces_novel": [],
                    "standing_triggers_novel": [],
                    "cost_novel": None,
                },
            },
            record_hash="d" * 64,
        )

    def run_act(self, verb, bundle_id, *, decision_citation):
        self.calls.append(("run_act", verb, bundle_id, decision_citation))
        self._act_counter += 1
        from chancellor.installs import ActOutcome

        return ActOutcome(
            act_id=f"{verb}-{bundle_id}-fake{self._act_counter}",
            verb=verb,
            bundle_id=bundle_id,
            receipt_id="1" * 64,
            receipt_seq=42,
            journal_dir=Path("/tmp"),
            result={"act_id": f"{verb}-{bundle_id}-fake{self._act_counter}"},
        )

    def rollback_install(self, bundle_id, install_act_id, *, decision_citation):
        self.calls.append(
            ("rollback_install", bundle_id, install_act_id, decision_citation)
        )
        from chancellor.installs import ActOutcome

        return ActOutcome(
            act_id=f"rollback-{bundle_id}-fake",
            verb="rollback",
            bundle_id=bundle_id,
            receipt_id="2" * 64,
            receipt_seq=43,
            journal_dir=Path("/tmp"),
            result={"act_id": f"rollback-{bundle_id}-fake"},
        )

    def disable(self, bundle_id):
        self.calls.append(("disable", bundle_id))
        self.disabled.append(bundle_id)
        return {"ok": True, "library_present": False}

    def enable(self, bundle_id):
        self.calls.append(("enable", bundle_id))
        return {"ok": True, "library_present": True}

    def census_pin(self, bundle_id):
        self.calls.append(("census_pin", bundle_id))
        return self.census_pins.get(bundle_id, PIN)

    def is_live(self, bundle_id):
        return {"query": "is-live", "answer": "LIVE"}


def _proposal(bundle_id="local-fake", pin=PIN, **kw) -> BundleProposal:
    manifest = {
        "schema": "e5.foundry.bundle.v1",
        "bundle_id": bundle_id,
        "kind": "skill",
        "provides": ["fake-capability"],
        "cost_surface": "none",
        "effect_class": "R",
    }
    return BundleProposal(
        bundle_id=bundle_id,
        source_dir=Path("/tmp"),
        manifest=manifest,
        manifest_pin=pin,
        **kw,
    )


def _governor(tmp_path, *, approver=None, gateway=None, scope=None):
    log = AuditLog(tmp_path / "audit.jsonl")
    gateway = gateway or FakeGateway()
    governor = InstallGovernor(
        audit_log=log,
        approver=approver or (lambda req: (True, "approved for the test")),
        human_id="test-human",
        manager=gateway,
        commission=Commission(
            receipt_id=COMMISSION_ID,
            scope_artifact_sha256="e" * 64,
            principle_hash="f" * 64,
        ),
        scope_bundles=scope
        if scope is not None
        else {"local-fake": {"kind": "skill"}, "local-fake-b": {"kind": "skill"}},
        scope_verbs={"install", "deprecate", "rollback"},
    )
    return governor, log, gateway


def _refusal_outcome(state: str, chancellor_state: str) -> PreflightOutcome:
    return PreflightOutcome(
        ok=False,
        bundle_id="local-fake",
        verb="install",
        foundry_state=state,
        refusal_state=chancellor_state,
        record_hash="9" * 64,
        detail=f"manager detail for {state}",
    )


# ------------------------------------------------------------ the register
@pytest.mark.parametrize(
    "foundry_state,chancellor_state",
    [
        ("preflight.engine-incompatible", REFUSAL_INSTALL_INCOMPATIBLE),
        ("preflight.host-unsupported", REFUSAL_INSTALL_INCOMPATIBLE),
        ("preflight.license-unverified", REFUSAL_INSTALL_UNLICENSED),
        ("preflight.content-hash-mismatch", REFUSAL_INSTALL_PIN_MISMATCH),
        ("preflight.payload-escape", REFUSAL_INSTALL_PAYLOAD_ESCAPE),
        (
            "preflight.build-script-unconsented",
            REFUSAL_INSTALL_UNCONSENTED_BUILD,
        ),
        ("preflight.snapshot-failed", REFUSAL_INSTALL_SNAPSHOT_FAILED),
    ],
)
def test_refusal_mapping_table(tmp_path, foundry_state, chancellor_state):
    """§1.4: each Foundry pre-flight state maps to exactly one
    Chancellor state; the refusal Decision names the Foundry state
    verbatim and cites the refusal record's hash; the gate is never
    invoked for a pre-flight refusal."""
    gateway = FakeGateway()
    gateway.preflight_outcomes["local-fake"] = _refusal_outcome(
        foundry_state, chancellor_state
    )

    def approver(_req):
        raise AssertionError("gate must not be invoked on a refusal")

    governor, log, _ = _governor(tmp_path, approver=approver, gateway=gateway)
    result = governor.run_arc(_proposal())
    assert result.stage_reached == "refused-preflight"
    assert result.refusal_state == chancellor_state
    entries = log.read_all()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["action_class"] == "capability_install"
    assert entry["approved"] is False
    assert entry["decider"] == "policy"
    assert entry["refusal_state"] == chancellor_state
    assert foundry_state in entry["rationale"]
    detail = json.loads(entry["detail"])
    assert detail["foundry_refusal_state"] == foundry_state
    assert detail["foundry_refusal_record_hash"] == "9" * 64
    assert not [c for c in gateway.calls if c[0] == "run_act"]


def test_scope_refusal_never_reaches_the_manager(tmp_path):
    """L2b's shape: an out-of-scope id refuses at the governor's own
    check — install-out-of-scope, zero manager calls, zero payload."""
    gateway = FakeGateway()
    governor, log, _ = _governor(tmp_path, gateway=gateway)
    result = governor.run_arc(_proposal(bundle_id="local-not-enumerated"))
    assert result.stage_reached == "refused-scope"
    assert result.refusal_state == REFUSAL_INSTALL_OUT_OF_SCOPE
    assert gateway.calls == []
    entry = log.read_all()[-1]
    assert entry["refusal_state"] == REFUSAL_INSTALL_OUT_OF_SCOPE


def test_install_class_is_a_human_gate(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    gatekeeper = Gatekeeper(audit_log=log)  # no approver attached
    decision = gatekeeper.authorize(
        EscalationRequest(
            action="capability install: local-fake",
            action_class=ActionClass.CAPABILITY_INSTALL,
        )
    )
    assert decision.approved is False
    assert decision.refusal_state == REFUSAL_NO_APPROVER
    assert ActionClass.CAPABILITY_INSTALL in {
        c for c in ActionClass if c.value == "capability_install"
    }


def test_gate_decline_installs_nothing(tmp_path):
    gateway = FakeGateway()
    governor, log, _ = _governor(
        tmp_path,
        approver=lambda req: (False, "not this one"),
        gateway=gateway,
    )
    result = governor.run_arc(_proposal())
    assert result.stage_reached == "denied-gate"
    assert result.refusal_state == REFUSAL_APPROVER_DECLINED
    assert not [c for c in gateway.calls if c[0] == "run_act"]


def test_cost_surface_refuses_before_the_gate(tmp_path):
    gateway = FakeGateway()

    def approver(_req):
        raise AssertionError("gate must not be invoked on a cost refusal")

    governor, log, _ = _governor(tmp_path, approver=approver, gateway=gateway)
    proposal = _proposal()
    object.__setattr__(
        proposal, "manifest", {**proposal.manifest, "cost_surface": "metered"}
    )
    result = governor.run_arc(proposal)
    assert result.refusal_state == REFUSAL_INSTALL_COST_REFUSED


# ---------------------------------------------------------------- the arc
def test_install_arc_and_probation_open(tmp_path):
    gateway = FakeGateway()
    governor, log, _ = _governor(tmp_path, gateway=gateway)
    arc = governor.run_arc(_proposal())
    assert arc.stage_reached == "installed-unverified"
    # The act was invoked under the decision's citation: the citation
    # the manager received names the decision entry's seq + hash.
    citation = [c for c in gateway.calls if c[0] == "run_act"][0][3]
    assert citation["kind"] == "chancellor-decision"
    assert citation["seq"] == arc.decision_entry["seq"]
    assert citation["entry_hash"] == arc.decision_entry["entry_hash"]
    assert citation["frame_id"] == receipts.FRAME_ID
    # The gate request bound bundle + pin + verb in canonical detail.
    detail = json.loads(arc.decision_entry["detail"])
    assert detail["bundle_id"] == "local-fake"
    assert detail["manifest_pin"] == PIN
    assert detail["verb"] == "install"
    assert detail["commission_receipt_id"] == COMMISSION_ID
    opened = governor.verify_live(
        _proposal(), arc, beat2_report=b"verifier report", beat2_passed=True
    )
    assert opened["entry_type"] == "capability_probation_opened"
    assert opened["decision_seq"] == arc.decision_entry["seq"]
    assert opened["install_receipt_id"] == "1" * 64
    state = governor.status("local-fake")
    assert state.standing == "probation"
    assert state.uses == 0 and state.strikes == 0
    result = verify_log(log.path)
    assert result.ok, result.failures


def test_beat2_failure_rolls_back_and_counts_an_attempt(tmp_path):
    gateway = FakeGateway()
    governor, log, _ = _governor(tmp_path, gateway=gateway)
    arc = governor.run_arc(_proposal())
    governor.verify_live(
        _proposal(), arc, beat2_report=b"failed report", beat2_passed=False
    )
    assert [c for c in gateway.calls if c[0] == "rollback_install"]
    entries = log.read_all()
    # The supervision fold reads the simultaneous escalation.
    sup = rebuild_supervision_state(entries)
    assert sup.escalations == 1
    assert count_consecutive_failed_attempts(entries, COMMISSION_ID) == 1
    assert governor.status("local-fake").standing == "unknown"


def test_budget_exhausted_after_three_failed_attempts(tmp_path):
    gateway = FakeGateway()
    governor, log, _ = _governor(tmp_path, gateway=gateway)
    for bundle in ("local-fake", "local-fake-b", "local-fake"):
        prop = _proposal(bundle_id=bundle)
        arc = governor.run_arc(prop)
        assert arc.stage_reached == "installed-unverified"
        governor.verify_live(prop, arc, beat2_report=b"no", beat2_passed=False)
    calls_before = len(gateway.calls)
    result = governor.run_arc(_proposal())
    assert result.stage_reached == "budget-exhausted"
    assert result.refusal_state == REFUSAL_INSTALL_BUDGET_EXHAUSTED
    # The refusal never reached the manager or the gate's act path.
    assert not [c for c in gateway.calls[calls_before:] if c[0] == "run_act"]


# ------------------------------------------------------------- probation
def _open_probation(tmp_path, gateway=None):
    gateway = gateway or FakeGateway()
    governor, log, gateway = _governor(tmp_path, gateway=gateway)
    arc = governor.run_arc(_proposal())
    governor.verify_live(_proposal(), arc, beat2_report=b"ok", beat2_passed=True)
    return governor, log, gateway


def test_probation_window_closes_at_ten_uses(tmp_path):
    governor, log, _ = _open_probation(tmp_path)
    for i in range(9):
        governor.record_use("local-fake", invocation=f"q{i}")
    state = governor.status("local-fake")
    assert state.standing == "probation" and state.uses == 9
    governor.record_use("local-fake", invocation="q9", grade="pass")
    state = governor.status("local-fake")
    assert state.standing == "standing"
    assert state.uses == 10 and state.strikes == 0
    closed = [
        e
        for e in log.read_all()
        if e.get("entry_type") == "capability_probation_closed"
    ]
    assert len(closed) == 1
    assert closed[0]["uses"] == 10 and closed[0]["strikes"] == 0


def test_suspension_at_exactly_strike_two(tmp_path):
    """The Stage 3 fault-injection gate: no suspension at one strike;
    a further use is receipted; suspension lands at exactly strike 2
    as one motion — entry, disable enforcement, escalation."""
    governor, log, gateway = _open_probation(tmp_path)
    governor.record_use("local-fake", invocation="bad-1", grade="fail")
    state = governor.status("local-fake")
    assert state.standing == "probation" and state.strikes == 1
    assert gateway.disabled == []
    governor.record_use("local-fake", invocation="between", grade="pass")
    governor.record_use("local-fake", invocation="bad-2", grade="fail")
    state = governor.status("local-fake")
    assert state.standing == "suspended"
    assert state.strikes == 2 and state.uses == 3
    assert gateway.disabled == ["local-fake"]
    entries = log.read_all()
    suspensions = [e for e in entries if e.get("entry_type") == "capability_suspension"]
    assert len(suspensions) == 1
    assert suspensions[0]["reason"] == "two-strikes"
    assert suspensions[0]["strike_seqs"] == state.strike_seqs
    # The chain shows a use between strike 1 and the suspension.
    strike1_seq = state.strike_seqs[0]
    suspension_seq = suspensions[0]["seq"]
    between = [
        e
        for e in entries
        if e.get("entry_type") == "capability_use"
        and strike1_seq < e["seq"] < suspension_seq
    ]
    assert len(between) >= 1
    assert rebuild_supervision_state(entries).escalations == 1


def test_pin_drift_suspends_at_strike_one(tmp_path):
    gateway = FakeGateway()
    governor, log, gateway = _open_probation(tmp_path, gateway=gateway)
    gateway.census_pins["local-fake"] = PIN_B  # the tree no longer matches
    governor.record_use("local-fake", invocation="drifted")
    state = governor.status("local-fake")
    assert state.standing == "suspended"
    suspensions = [
        e for e in log.read_all() if e.get("entry_type") == "capability_suspension"
    ]
    assert suspensions[0]["reason"] == "pin-drift"
    assert len(suspensions[0]["strike_seqs"]) == 1


def test_strikes_survive_a_governor_restart(tmp_path):
    governor, log, gateway = _open_probation(tmp_path)
    governor.record_use("local-fake", invocation="bad-1", grade="fail")
    # A fresh governor over a fresh AuditLog on the same file: the
    # fold rebuilds the strike from the chain alone.
    governor2, log2, _ = _governor(tmp_path, gateway=gateway)
    state = governor2.status("local-fake")
    assert state.standing == "probation" and state.strikes == 1
    governor2.record_use("local-fake", invocation="bad-2", grade="fail")
    assert governor2.status("local-fake").standing == "suspended"


def test_gated_uses_count_and_refusals_strike(tmp_path):
    governor, log, _ = _open_probation(tmp_path)
    decision = governor.submit_gated_use(
        "local-fake",
        EscalationRequest(
            action="use the capability to compute",
            action_class=ActionClass.COMPUTE,
        ),
    )
    assert decision.approved is True
    state = governor.status("local-fake")
    assert state.uses == 1 and state.strikes == 0
    # A gate-refused gated use is a strike (the approver here declines
    # via a second governor whose approver refuses).
    governor2 = InstallGovernor(
        audit_log=log,
        approver=lambda req: (False, "no"),
        human_id="test-human",
        manager=FakeGateway(),
        commission=Commission(receipt_id=COMMISSION_ID, scope_artifact_sha256="e" * 64),
        scope_bundles={"local-fake": {"kind": "skill"}},
        scope_verbs={"install"},
    )
    decision2 = governor2.submit_gated_use(
        "local-fake",
        EscalationRequest(
            action="use the capability to spend",
            action_class=ActionClass.SPEND,
        ),
    )
    assert decision2.approved is False
    state = governor.status("local-fake")
    assert state.uses == 2 and state.strikes == 1


def test_am2_union_rides_the_gate_receipt(tmp_path):
    """The bundle's declared permissions union over the class's empty
    static floor through the request-side seam (§1.4 AM-2)."""
    governor, log, _ = _governor(tmp_path)
    arc = governor.run_arc(_proposal(permissions_requested=("money", "send")))
    entry = arc.decision_entry
    assert entry["effect_axes"] == [
        "external_visibility",
        "money_movement",
    ]
    assert entry["capability_id"] == "local-fake"


# ------------------------------------------------------- the §7 diff gate
def test_eight_class_receipts_byte_identical_outside_the_frame(tmp_path):
    """The §7 diff gate, as a test: regenerate the golden population
    (the eight pre-existing classes + the caller-shaped entries)
    under the current code and diff against the fixture captured
    from the BASE code. Every field must be byte-identical except
    the frame citation and the hashes that commit it — the frame
    rotation is the intended visible change; the AM-2 seam moves
    nothing for classes that never set its fields."""
    fixture = (
        Path(__file__).parent / "fixtures" / "installs" / "eight-class-golden.jsonl"
    )
    golden = [json.loads(ln) for ln in fixture.read_text().splitlines() if ln.strip()]
    log = AuditLog(tmp_path / "regen.jsonl")
    ts = 1730000000.0
    eight = [
        ActionClass.READ,
        ActionClass.DRAFT,
        ActionClass.COMPUTE,
        ActionClass.SPEND,
        ActionClass.EXTERNAL_SEND,
        ActionClass.PUBLISH,
        ActionClass.IRREVERSIBLE,
        ActionClass.CREDENTIAL,
    ]
    for i, cls in enumerate(eight):
        req = EscalationRequest(
            action=f"golden {cls.value}",
            action_class=cls,
            detail=f"detail {cls.value}",
            cost_usd=1.5,
            node_id="n1",
        )
        log.record(Decision(req, True, "policy", "approved by policy", ts + i))
        log.record(
            Decision(
                req,
                False,
                "human",
                "declined",
                ts + 100 + i,
                refusal_state=REFUSAL_APPROVER_DECLINED,
            )
        )
    log.record_entry(
        receipts.freeze_manifest_fields(
            files={"a.txt": "0" * 64, "b.txt": "f" * 64},
            suite_id="golden",
            head="abc123",
            recorded_by="seat",
            ts=ts,
        )
    )
    log.record_entry(
        receipts.test_run_fields(
            suite="golden",
            command="pytest -q",
            manifest_sha256="a" * 64,
            report_sha256="b" * 64,
            passed=3,
            failed=0,
            seat="seat",
            report_path="r.md",
            ts=ts,
        )
    )
    regen = log.read_all()
    assert len(regen) == len(golden)
    mask = {"frame_id", "frame_hash", "entry_hash", "prev_hash"}
    for old, new in zip(golden, regen, strict=True):
        for key in set(old) | set(new):
            if key in mask:
                continue
            assert old.get(key) == new.get(key), (
                f"field {key} changed for seq {old.get('seq')}"
            )
    assert {(e["frame_id"], e["frame_hash"]) for e in regen} == {
        (receipts.FRAME_ID, receipts.FRAME_HASH)
    }


# ------------------------------------------------------------ bridge audit
def _bridge_entries(tmp_path):
    """A chain with one approved install decision + probation opened."""
    governor, log, _ = _governor(tmp_path)
    arc = governor.run_arc(_proposal())
    governor.verify_live(_proposal(), arc, beat2_report=b"ok", beat2_passed=True)
    return log.read_all(), arc


def _bridge_journal(arc, *, seq=None, entry_hash=None, at=None):
    if at is None:
        # The pre-flight must not pre-date the decision it follows, so
        # derive its time from the decision entry itself (+1h). A fixed
        # wall-clock date here time-bombed the clean-pair test: it only
        # passed until that date (2026-11-02T20:00Z) was reached, then
        # failed deterministically on every later run.
        at = datetime.fromtimestamp(
            float(arc.decision_entry["ts"]) + 3600, tz=UTC
        ).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        arc.act.act_id: {
            "preflight": {"at": at, "verdict": "PASS"},
            "chancellor_decision": {
                "kind": "chancellor-decision",
                "log_ref": "chain",
                "seq": arc.decision_entry["seq"] if seq is None else seq,
                "entry_hash": (
                    arc.decision_entry["entry_hash"]
                    if entry_hash is None
                    else entry_hash
                ),
                "frame_id": receipts.FRAME_ID,
                "frame_hash": receipts.FRAME_HASH,
            },
        }
    }


def _bridge_records(arc):
    return [
        {
            "type": "act",
            "act_id": arc.act.act_id,
            "verb": "install",
            "bundle_id": "local-fake",
            "receipt_id": arc.act.receipt_id,
            "receipt_seq": 42,
            "statement": {"verb": "install", "bundle_id": "local-fake"},
        }
    ]


def test_bridge_audit_resolves_a_clean_pair(tmp_path):
    entries, arc = _bridge_entries(tmp_path)
    result = audit_install_bridge(entries, _bridge_records(arc), _bridge_journal(arc))
    assert result.ok, result.failures
    assert result.acts_checked == 1 and result.citations_resolved == 1


def test_bridge_audit_catches_a_broken_citation(tmp_path):
    entries, arc = _bridge_entries(tmp_path)
    journals = _bridge_journal(arc, entry_hash="0" * 64)
    result = audit_install_bridge(entries, _bridge_records(arc), journals)
    assert not result.ok
    assert len(result.failures) == 1
    assert "bridge_citation_unresolved" in result.failures[0]


def test_bridge_audit_late_decision_is_no_decision(tmp_path):
    entries, arc = _bridge_entries(tmp_path)
    # The decision's ts (test clock: real time, 2026-11-02 or later in
    # the grading environment) — force lateness by back-dating the
    # act's pre-flight instead: a pre-flight BEFORE the decision.
    journals = _bridge_journal(arc, at="2000-01-01T00:00:00Z")
    result = audit_install_bridge(entries, _bridge_records(arc), journals)
    assert not result.ok
    assert any("bridge_precedence_late" in f for f in result.failures)


def test_bridge_audit_pairs_refusals(tmp_path):
    gateway = FakeGateway()
    gateway.preflight_outcomes["local-fake"] = _refusal_outcome(
        "preflight.content-hash-mismatch", REFUSAL_INSTALL_PIN_MISMATCH
    )
    governor, log, _ = _governor(tmp_path, gateway=gateway)
    governor.run_arc(_proposal())
    records = [
        {
            "type": "refusal",
            "act_id": "preflight-x",
            "verb": "install",
            "bundle_id": "local-fake",
            "reason": "preflight.content-hash-mismatch",
            "record_hash": "9" * 64,
        }
    ]
    result = audit_install_bridge(log.read_all(), records, {})
    assert result.ok, result.failures
    assert result.refusals_paired == 1
    # An unpaired refusal record fails the audit.
    records[0] = {**records[0], "record_hash": "8" * 64}
    result2 = audit_install_bridge(log.read_all(), records, {})
    assert not result2.ok
    assert any("bridge_refusal_unpaired" in f for f in result2.failures)


def test_installs_status_fold_matches_governor(tmp_path):
    """P6's print surface reads the same fold the governor acts on."""
    governor, log, _ = _open_probation(tmp_path)
    governor.record_use("local-fake", invocation="q", grade="fail")
    states = installs.fold_all_probation(log.read_all())
    lines = installs.format_status_lines(states, head=log.read_all()[-1]["entry_hash"])
    assert len(lines) == 1
    assert "standing=probation" in lines[0]
    assert "uses=1/10" in lines[0] and "strikes=1" in lines[0]
    assert PIN in lines[0]
