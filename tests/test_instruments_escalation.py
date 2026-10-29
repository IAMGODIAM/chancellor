from warden.escalation import (ActionClass, AuditLog, EscalationRequest,
                               Gatekeeper)
from warden.instruments import (CheckResult, InstrumentPanel, default_panel)


def test_panel_pass_and_fail():
    panel = default_panel(max_cost_usd=1.0)
    assert panel.run_all({"text": "hello", "cost_usd": 0.5}).ok
    assert not panel.run_all({"text": "  ", "cost_usd": 0.5}).ok
    assert not panel.run_all({"text": "hello", "cost_usd": 2.0}).ok


def test_instrument_error_is_failure_fail_closed():
    def broken(_artifact):
        raise RuntimeError("gauge exploded")

    panel = InstrumentPanel().register("broken_gauge", broken)
    result = panel.run_all({"text": "fine"})
    assert not result.ok
    assert "instrument error" in result.failures[0].detail


def test_banned_terms_check():
    panel = default_panel(banned_terms=("lorem",))
    assert not panel.run_all({"text": "Lorem ipsum"}).ok


def _req(cls, action="do the thing"):
    return EscalationRequest(action=action, action_class=cls)


def test_auto_classes_pass_by_policy():
    gk = Gatekeeper()
    assert gk.authorize(_req(ActionClass.DRAFT)).approved
    assert gk.authorize(_req(ActionClass.READ)).approved


def test_human_gate_without_approver_denies_fail_closed(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    gk = Gatekeeper(audit_log=log)
    decision = gk.authorize(_req(ActionClass.SPEND))
    assert not decision.approved
    assert len(log.read_all()) == 1
    assert log.read_all()[0]["approved"] is False


def test_human_gate_with_approver(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    gk = Gatekeeper(audit_log=log,
                    approver=lambda req: (True, "approved in demo"),
                    human_id="israel")
    decision = gk.authorize(_req(ActionClass.EXTERNAL_SEND))
    assert decision.approved and decision.decider == "israel"
    entries = log.read_all()
    assert entries[0]["action_class"] == "external_send"
