"""Gate integrity: the action class comes from the brokered tool and a
frozen policy table; declared/brokered mismatches, inert nodes, swallowed
denials and unbrokered effects are denied or halt with a receipt; the
broker's execution records land on the chain."""

import contextlib
from types import MappingProxyType

import pytest

from chancellor import receipts
from chancellor.escalation import (
    REFUSAL_BROKERED_DENIAL,
    REFUSAL_DECLARATION_MISMATCH,
    REFUSAL_INERT_VIOLATION,
    REFUSAL_UNBROKERED_EFFECT,
    REFUSAL_UNCLASSIFIED,
    ActionClass,
    ActionPolicy,
    AuditLog,
    EscalationRequest,
    Gatekeeper,
)
from chancellor.grader import OUTPUT_RUBRIC
from chancellor.instruments import default_panel
from chancellor.interception import ObservedEffect, ToolBroker, ToolDenied, digest
from chancellor.orchestrator import CrewRunner
from chancellor.task_graph import TaskGraph

GOOD = {"correctness": 9, "completeness": 9, "clarity": 9, "safety": 10}


def _setup(tmp_path, *, approver=None):
    log = AuditLog(tmp_path / "audit.jsonl")
    gk = Gatekeeper(audit_log=log, approver=approver)
    broker = ToolBroker(gatekeeper=gk)
    ran: list[tuple[str, dict]] = []
    for name in ("compute", "read_file", "draft_text", "wire_transfer", "send_email"):
        broker.register(name, lambda _n=name, **kw: ran.append((_n, kw)) or "done")
    return log, gk, broker, ran


def _runner(graph, workers, gk, broker=None, **kwargs):
    return CrewRunner.governed(
        graph,
        workers,
        panel=default_panel(),
        rubric=OUTPUT_RUBRIC,
        gatekeeper=gk,
        broker=broker,
        score_provider=lambda node, artifact: GOOD,
        **kwargs,
    )


def _graph(*, inert=False, worker="w"):
    g = TaskGraph("t")
    g.task("n", "N", worker=worker, inert=inert)
    return g


def _artifact(action=None):
    art = {"text": "work done", "cost_usd": 0.0}
    if action is not None:
        art["action"] = action
    return art


def _last_receipt(log):
    return [e for e in log.read_all() if e.get("entry_type") != "tool_outcome"][-1]


# ------------------------------------------- 2. classification and mismatch
def test_declared_class_cannot_loosen_a_brokered_call(tmp_path):
    """The node brokered a wire transfer and declares it as compute."""
    log, gk, broker, _ = _setup(tmp_path, approver=lambda _r: (True, "ok"))

    def worker(node):
        broker.call(node.id, "wire_transfer", {"amount": 5000})
        return _artifact(
            {"action": "wire $5000", "action_class": "compute", "tool": "compute"}
        )

    report = _runner(_graph(), {"w": worker}, gk, broker).run()
    assert report.halted and report.blocked == ["n"] and not report.completed
    receipt = _last_receipt(log)
    assert receipt["approved"] is False
    assert receipt["refusal_state"] == REFUSAL_DECLARATION_MISMATCH


@pytest.mark.parametrize(
    "action",
    [
        {"action": "wire $5000", "action_class": "compute", "tool": "compute"},
        {"action": "wire $5000", "tool": "read_file"},
        {"action": "wire $5000", "tool": "draft_text", "effects": []},
        {"action": "wire $5000", "action_class": "compute"},
    ],
)
def test_auto_approved_declaration_without_a_brokered_call_is_denied(tmp_path, action):
    log, gk, broker, ran = _setup(tmp_path)
    report = _runner(_graph(), {"w": lambda n: _artifact(action)}, gk, broker).run()
    assert report.halted and not report.completed
    receipt = _last_receipt(log)
    assert receipt["approved"] is False
    assert receipt["refusal_state"] in {
        REFUSAL_DECLARATION_MISMATCH,
        REFUSAL_UNCLASSIFIED,
    }
    assert ran == []


def test_declared_tool_that_was_not_brokered_is_denied(tmp_path):
    log, gk, broker, _ = _setup(tmp_path, approver=lambda _r: (True, "ok"))

    def worker(node):
        broker.call(node.id, "compute", {"x": 1})
        return _artifact({"action": "send it", "tool": "send_email"})

    report = _runner(_graph(), {"w": worker}, gk, broker).run()
    assert report.blocked == ["n"]
    assert _last_receipt(log)["refusal_state"] == REFUSAL_DECLARATION_MISMATCH


def test_matching_declaration_completes_and_class_comes_from_the_table(tmp_path):
    log, gk, broker, ran = _setup(tmp_path, approver=lambda _r: (True, "ok"))

    def worker(node):
        broker.call(node.id, "wire_transfer", {"amount": 5})
        return _artifact(
            {"action": "pay", "action_class": "spend", "tool": "wire_transfer"}
        )

    report = _runner(_graph(), {"w": worker}, gk, broker).run()
    assert report.ok and report.completed == ["n"]
    assert len(ran) == 1
    decision = log.read_all()[0]
    assert decision["action_class"] == "spend" and decision["tool"] == "wire_transfer"


def test_a_declaration_may_still_add_a_human_gate_without_a_broker(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    gk = Gatekeeper(audit_log=log)  # no approver: the human gate denies
    action = {"action": "send", "action_class": "external_send", "tool": "send_email"}
    report = _runner(_graph(), {"w": lambda n: _artifact(action)}, gk).run()
    assert report.blocked == ["n"]
    assert _last_receipt(log)["action_class"] == "external_send"


def test_policy_table_is_frozen_and_not_reachable_through_the_gatekeeper(tmp_path):
    source = {"compute": ActionClass.COMPUTE}
    policy = ActionPolicy(tools=source)
    source["compute"] = ActionClass.SPEND
    source["wire_transfer"] = ActionClass.COMPUTE
    assert policy.tools["compute"] is ActionClass.COMPUTE
    assert "wire_transfer" not in policy.tools
    assert isinstance(policy.tools, MappingProxyType)
    with pytest.raises(TypeError):
        policy.tools["compute"] = ActionClass.SPEND  # type: ignore[index]
    with pytest.raises(TypeError):
        policy.effects["money_movement"] = ActionClass.READ  # type: ignore[index]
    gk = Gatekeeper(policy=policy)
    with pytest.raises(AttributeError):
        gk.policy = ActionPolicy()  # type: ignore[misc]
    from chancellor import escalation

    with pytest.raises(TypeError):
        escalation.DEFAULT_TOOL_POLICY["wire_transfer"] = ActionClass.READ  # type: ignore[index]
    with pytest.raises(TypeError):
        escalation._STRICTNESS[ActionClass.SPEND] = 0  # type: ignore[index]


def test_a_worker_gets_nothing_that_reaches_the_table(tmp_path):
    seen = {}

    def worker(node):
        seen["node"] = node
        return _artifact()

    _, gk, broker, _ = _setup(tmp_path)
    _runner(_graph(inert=True), {"w": worker}, gk, broker).run()
    node = seen["node"]
    assert not hasattr(node, "policy") and not hasattr(node, "gatekeeper")


# ---------------------------------------------------- swallowed denial
def test_node_with_a_denied_brokered_row_is_denied_even_if_swallowed(tmp_path):
    log, gk, broker, ran = _setup(tmp_path)  # no approver: the wire is refused

    def worker(node):
        with contextlib.suppress(ToolDenied):
            broker.call(node.id, "wire_transfer", {"amount": 5})
        broker.call(node.id, "compute", {"x": 1})  # a benign call afterwards
        return _artifact(
            {"action": "calc", "action_class": "compute", "tool": "compute"}
        )

    report = _runner(_graph(), {"w": worker}, gk, broker).run()
    assert report.halted and report.blocked == ["n"] and not report.completed
    assert _last_receipt(log)["refusal_state"] == REFUSAL_BROKERED_DENIAL
    assert ("wire_transfer", {"amount": 5}) not in ran


def test_denied_row_blocks_a_node_that_declares_no_action(tmp_path):
    log, gk, broker, _ = _setup(tmp_path)

    def worker(node):
        with contextlib.suppress(ToolDenied):
            broker.call(node.id, "wire_transfer", {"amount": 5})
        return _artifact()

    report = _runner(_graph(), {"w": worker}, gk, broker).run()
    assert report.blocked == ["n"]
    assert _last_receipt(log)["refusal_state"] == REFUSAL_BROKERED_DENIAL


# ----------------------------------------------------------- 3. inert
def test_inert_node_that_made_a_brokered_call_is_denied(tmp_path):
    log, gk, broker, _ = _setup(tmp_path)

    def worker(node):
        broker.call(node.id, "compute", {"x": 1})
        return _artifact()

    report = _runner(_graph(inert=True), {"w": worker}, gk, broker).run()
    assert report.halted and report.blocked == ["n"] and not report.completed
    receipt = _last_receipt(log)
    assert receipt["approved"] is False
    assert receipt["refusal_state"] == REFUSAL_INERT_VIOLATION


def test_inert_node_with_no_brokered_call_still_completes(tmp_path):
    log, gk, broker, _ = _setup(tmp_path)
    report = _runner(_graph(inert=True), {"w": lambda n: _artifact()}, gk, broker).run()
    assert report.ok and report.completed == ["n"]
    assert _last_receipt(log)["approved"] is True


def test_inert_is_refused_for_a_worker_holding_raw_tool_handles(tmp_path):
    log, gk, broker, _ = _setup(tmp_path)
    started = []

    def worker(node):
        started.append(node.id)
        return _artifact()

    report = _runner(
        _graph(inert=True),
        {"w": worker},
        gk,
        broker,
        raw_tool_handles={"w": ["wire_transfer"]},
    ).run()
    assert started == []  # refused before the worker ran
    assert report.halted and report.blocked == ["n"]
    receipt = _last_receipt(log)
    assert receipt["refusal_state"] == REFUSAL_INERT_VIOLATION


def test_inert_is_refused_for_a_worker_that_carries_its_handles(tmp_path):
    log, gk, broker, _ = _setup(tmp_path)

    def worker(node):
        return _artifact()

    worker.raw_tool_handles = ("send_email",)  # type: ignore[attr-defined]
    report = _runner(_graph(inert=True), {"w": worker}, gk, broker).run()
    assert report.halted and _last_receipt(log)["refusal_state"] == (
        REFUSAL_INERT_VIOLATION
    )


def test_a_non_inert_node_with_raw_handles_is_allowed_to_run(tmp_path):
    _, gk, broker, _ = _setup(tmp_path)

    def worker(node):
        broker.call(node.id, "compute", {"x": 1})
        return _artifact({"action": "calc", "tool": "compute"})

    report = _runner(
        _graph(), {"w": worker}, gk, broker, raw_tool_handles={"w": ["compute"]}
    ).run()
    assert report.ok


# ------------------------------------------------ 4. unbrokered effects
def test_unbrokered_effect_halts_with_a_receipt(tmp_path):
    log, gk, broker, _ = _setup(tmp_path, approver=lambda _r: (True, "ok"))
    effects: list[ObservedEffect] = []

    def worker(node):
        broker.call(node.id, "compute", {"x": 1})
        effects.append(ObservedEffect("wire_transfer", description="wire $5000"))
        return _artifact({"action": "calc", "tool": "compute"})

    report = _runner(
        _graph(), {"w": worker}, gk, broker, effect_observers=[lambda n: effects]
    ).run()
    assert report.halted and report.failed == ["n"] and not report.completed
    receipt = _last_receipt(log)
    assert receipt["approved"] is False
    assert receipt["refusal_state"] == REFUSAL_UNBROKERED_EFFECT
    assert "wire $5000" in receipt["rationale"]


def test_unbrokered_effect_on_a_node_with_no_broker_calls_halts(tmp_path):
    log, gk, broker, _ = _setup(tmp_path)
    report = _runner(
        _graph(inert=True),
        {"w": lambda n: _artifact()},
        gk,
        broker,
        effect_observers=[lambda n: [ObservedEffect("send_email")]],
    ).run()
    assert report.failed == ["n"]
    assert _last_receipt(log)["refusal_state"] == REFUSAL_UNBROKERED_EFFECT


def test_observed_effect_that_matches_a_brokered_call_passes(tmp_path):
    _, gk, broker, _ = _setup(tmp_path, approver=lambda _r: (True, "ok"))
    args = {"amount": 5}

    def worker(node):
        broker.call(node.id, "wire_transfer", args)
        return _artifact({"action": "pay", "tool": "wire_transfer"})

    report = _runner(
        _graph(),
        {"w": worker},
        gk,
        broker,
        effect_observers=[lambda n: [ObservedEffect("wire_transfer", digest(args))]],
    ).run()
    assert report.ok


def test_observed_effect_with_other_arguments_halts(tmp_path):
    _, gk, broker, _ = _setup(tmp_path, approver=lambda _r: (True, "ok"))

    def worker(node):
        broker.call(node.id, "wire_transfer", {"amount": 5})
        return _artifact({"action": "pay", "tool": "wire_transfer"})

    report = _runner(
        _graph(),
        {"w": worker},
        gk,
        broker,
        effect_observers=[
            lambda n: [ObservedEffect("wire_transfer", digest({"amount": 5000}))]
        ],
    ).run()
    assert report.halted and report.failed == ["n"]


def test_failing_observer_halts(tmp_path):
    _, gk, broker, _ = _setup(tmp_path)

    def observer(node):
        raise RuntimeError("probe down")

    report = _runner(
        _graph(inert=True),
        {"w": lambda n: _artifact()},
        gk,
        broker,
        effect_observers=[observer],
    ).run()
    assert report.halted and report.failed == ["n"]


# ------------------------------------------- 5. execution on the chain
def test_outcome_records_digest_of_what_the_tool_received(tmp_path):
    log, gk, broker, _ = _setup(tmp_path, approver=lambda _r: (True, "ok"))
    broker.call("n", "wire_transfer", {"amount": 5, "to": "acct"})
    decision, outcome = log.read_all()
    assert outcome["executed_args_sha256"] == digest({"amount": 5, "to": "acct"})
    assert outcome["approved_args_sha256"] == decision["args_sha256"]
    assert outcome["result_status"] == "ok"
    assert outcome["result_sha256"] == digest("done")


def test_outcome_records_a_tool_error(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    gk = Gatekeeper(audit_log=log)
    broker = ToolBroker(gatekeeper=gk)

    def boom(**_kw):
        raise ValueError("no route")

    broker.register("compute", boom)
    with pytest.raises(ValueError):
        broker.call("n", "compute", {"x": 1})
    outcome = log.read_all()[-1]
    assert outcome["result_status"] == "error" and "no route" in outcome["error"]
    assert outcome["executed_args_sha256"] == digest({"x": 1})


def test_arguments_changed_during_approval_are_refused_and_recorded(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    shared = {"amount": 5, "memo": ["a"]}
    gk = Gatekeeper(
        audit_log=log,
        approver=lambda _r: (shared["memo"].append("b") or True, "ok"),
    )
    broker = ToolBroker(gatekeeper=gk)
    ran = []
    broker.register("wire_transfer", lambda **kw: ran.append(kw))
    with pytest.raises(ToolDenied):
        broker.call("n", "wire_transfer", shared)
    assert ran == []
    outcome = log.read_all()[-1]
    assert outcome["result_status"] == receipts.OUTCOME_REFUSED
    assert outcome["executed_args_sha256"] != outcome["approved_args_sha256"]


def test_denied_call_writes_no_outcome(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    broker = ToolBroker(gatekeeper=Gatekeeper(audit_log=log))
    broker.register("wire_transfer", lambda **_kw: "x")
    with pytest.raises(ToolDenied):
        broker.call("n", "wire_transfer", {"amount": 1})
    entries = log.read_all()
    assert len(entries) == 1 and entries[0]["approved"] is False


def test_outcome_write_failure_halts(tmp_path):
    from chancellor.escalation import AuditWriteError

    log = AuditLog(tmp_path / "a.jsonl")
    gk = Gatekeeper(audit_log=log)
    broker = ToolBroker(gatekeeper=gk)
    broker.register("compute", lambda **_kw: "x")

    def broken(_fields):
        raise OSError("disk full")

    log.record_entry = broken  # type: ignore[method-assign]
    with pytest.raises(AuditWriteError):
        broker.call("n", "compute", {"x": 1})


def test_request_carries_a_call_id_only_for_brokered_calls():
    assert EscalationRequest(action="x").call_id is None


def test_approval_shows_broker_generated_arguments(tmp_path):
    import json

    seen = []
    _, _, broker, _ = _setup(
        tmp_path, approver=lambda request: seen.append(request) or (True, "ok")
    )
    args = {"to": "reader@example.test", "body": "report"}
    broker.call("n", "send_email", args, action="caller summary", detail="caller note")
    assert seen[0].action == "call send_email"
    assert seen[0].detail.startswith("Canonical arguments: ")
    encoded = seen[0].detail.splitlines()[0].removeprefix("Canonical arguments: ")
    assert json.loads(encoded) == args
    assert seen[0].args_sha256 == digest(json.loads(encoded))


def test_each_observed_effect_needs_a_distinct_broker_call(tmp_path):
    _, _, broker, _ = _setup(tmp_path)
    args = {"value": 1}
    broker.call("n", "compute", args)
    observed = [ObservedEffect("compute", digest(args))] * 2
    assert len(broker.unbrokered("n", 0, observed)) == 1


def test_demo_help_does_not_run_the_demo(monkeypatch, capsys):
    from chancellor import cli

    def unexpected(**kwargs):
        pytest.fail("help must not run the demo")

    monkeypatch.setattr(cli, "run_exhibit", unexpected)
    assert cli.main(["demo", "--help"]) == 0
    assert "usage: chancellor demo" in capsys.readouterr().out


def test_supervise_help_does_not_hide_unknown_arguments(capsys):
    from chancellor.cli import main

    assert main(["supervise", "--help", "--unknown"]) == 2
    assert "--help takes no other options" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["eval-a", "eval-b"])
def test_eval_help_does_not_hide_unknown_arguments(command, capsys):
    from chancellor.cli import main

    assert main([command, "--help", "--unknown"]) == 2
    assert "unknown argument" in capsys.readouterr().err


def test_governed_runner_reports_missing_effect_coverage(tmp_path, caplog):
    _, gatekeeper, _, _ = _setup(tmp_path)
    _runner(_graph(), {"w": lambda node: _artifact()}, gatekeeper)
    assert "no effect observer or raw tool registration" in caplog.text
