"""Follow-up hardening tests: the Supervisor requires an explicit signer,
and workers reach registered tools only through the broker's per-node
handle."""

import dataclasses

import pytest

from chancellor import receipts
from chancellor.escalation import REFUSAL_RECONCILE_MISMATCH, AuditLog, Gatekeeper
from chancellor.grader import OUTPUT_RUBRIC
from chancellor.instruments import default_panel
from chancellor.interception import NodeTools, ToolBroker, ToolDenied
from chancellor.orchestrator import CrewRunner, brokered_worker
from chancellor.supervise import SignerRequiredError, Supervisor, SupervisorConfig
from chancellor.task_graph import TaskGraph

GOOD = {"correctness": 9, "completeness": 9, "clarity": 9, "safety": 10}
THROWAWAY = "throwaway-test-value-not-a-real-key"


# ------------------------------------------------ 1. mandatory signer
def _config(tmp_path):
    return SupervisorConfig(agent_command=["true"], state_dir=tmp_path)


def test_supervisor_without_signer_raises_a_clear_error(tmp_path):
    with pytest.raises(SignerRequiredError) as exc:
        Supervisor(_config(tmp_path))
    assert "explicit signer" in str(exc.value)
    assert "with_dev_signer" in str(exc.value)


def test_supervisor_with_signer_none_raises(tmp_path):
    with pytest.raises(SignerRequiredError):
        Supervisor(_config(tmp_path), signer=None)


def test_supervisor_accepts_an_explicit_signer(tmp_path):
    signer = receipts.DevHmacSigner(secret=THROWAWAY.encode())
    sup = Supervisor(_config(tmp_path), signer=signer)
    assert sup._signer is signer


def test_with_dev_signer_is_the_explicit_dev_path(tmp_path):
    sup = Supervisor.with_dev_signer(_config(tmp_path))
    assert sup._signer.key_id == receipts.DEV_SIGNER_KEY_ID


def test_supervise_cli_still_requires_an_operator_key(monkeypatch, capsys):
    from chancellor.cli import SUPERVISE_KEY_ENV
    from chancellor.cli import main as cli_main

    monkeypatch.delenv(SUPERVISE_KEY_ENV, raising=False)
    assert cli_main(["supervise", "--", "true"]) == 2
    assert "operator signing key" in capsys.readouterr().err


# ------------------------------------------------ 2. broker-only tools
def _broker(tmp_path, approver=None):
    log = AuditLog(tmp_path / "a.jsonl")
    broker = ToolBroker(Gatekeeper(audit_log=log, approver=approver))
    ran: list[dict] = []
    broker.register("wire_transfer", lambda **kw: ran.append(kw) or {"ok": True})
    return broker, log, ran


def _runner(graph, workers, broker):
    return CrewRunner.governed(
        graph,
        workers,
        panel=default_panel(),
        rubric=OUTPUT_RUBRIC,
        gatekeeper=broker.gatekeeper,
        broker=broker,
        score_provider=lambda node, artifact: GOOD,
    )


def _graph():
    g = TaskGraph("t")
    g.task("n", "N", worker="w")
    return g


def test_broker_does_not_expose_registered_callables(tmp_path):
    broker, _, _ = _broker(tmp_path)
    assert not hasattr(broker, "tools")
    assert "lambda" not in repr(broker)
    assert "tools" not in {f.name for f in dataclasses.fields(broker) if f.init}


def test_worker_handle_carries_no_tool_callable(tmp_path):
    broker, _, _ = _broker(tmp_path)
    handle = broker.session("n")
    assert isinstance(handle, NodeTools)
    public = [a for a in dir(handle) if not a.startswith("_")]
    assert sorted(public) == ["call", "has_tool", "node_id", "revoke"]
    assert not hasattr(handle, "__dict__")


def test_worker_call_is_checked_before_the_tool_runs(tmp_path):
    broker, log, ran = _broker(tmp_path)  # no approver: spend is refused
    seen: list[str] = []

    @brokered_worker
    def worker(node, tools):
        try:
            tools.call("wire_transfer", {"amount": 5})
        except ToolDenied as exc:
            seen.append(str(exc))
        return {"text": "attempted", "cost_usd": 0.0}

    _runner(_graph(), {"w": worker}, broker).run()
    assert seen and ran == []  # refused; the tool never executed
    assert log.read_all()[0]["approved"] is False
    assert broker.ledger[0].started is False


def test_approved_worker_call_runs_through_the_broker(tmp_path):
    broker, log, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))

    @brokered_worker
    def worker(node, tools):
        tools.call("wire_transfer", {"amount": 5})
        return {
            "text": "paid",
            "cost_usd": 0.0,
            "action": {"action": "pay", "tool": "wire_transfer"},
        }

    report = _runner(_graph(), {"w": worker}, broker).run()
    assert report.ok and report.completed == ["n"]
    assert ran == [{"amount": 5}]
    assert len(broker.ledger) == 1 and broker.ledger[0].node_id == "n"


def test_handle_is_bound_to_its_node(tmp_path):
    broker, _, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))
    handle = broker.session("node-a")
    handle.call("wire_transfer", {"amount": 1})
    assert [r.node_id for r in broker.ledger] == ["node-a"]
    with pytest.raises(TypeError):
        handle.call("wire_transfer", {"amount": 1}, node_id="node-b")  # type: ignore[call-arg]


def test_handle_is_revoked_when_the_worker_returns(tmp_path):
    broker, _, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))
    kept: list[NodeTools] = []

    @brokered_worker
    def worker(node, tools):
        kept.append(tools)
        return {"text": "ok", "cost_usd": 0.0}

    _runner(_graph(), {"w": worker}, broker).run()
    with pytest.raises(ToolDenied):
        kept[0].call("wire_transfer", {"amount": 5})
    assert ran == [] and not kept[0].has_tool("wire_transfer")


def test_brokered_worker_without_a_broker_fails_closed(tmp_path):
    called: list[int] = []

    @brokered_worker
    def worker(node, tools):
        called.append(1)
        return {"text": "ok", "cost_usd": 0.0}

    runner = CrewRunner.ungoverned(_graph(), {"w": worker})
    report = runner.run()
    assert called == [] and report.halted and report.failed == ["n"]


def test_declared_brokered_tool_that_skipped_the_broker_halts(tmp_path):
    broker, log, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))

    def worker(node):  # plain worker: made no brokered call
        return {
            "text": "paid",
            "cost_usd": 0.0,
            "action": {"action": "pay", "tool": "wire_transfer"},
        }

    report = _runner(_graph(), {"w": worker}, broker).run()
    assert report.halted and not report.completed
    assert log.read_all()[-1]["refusal_state"] == REFUSAL_RECONCILE_MISMATCH


def test_plain_workers_are_unchanged(tmp_path):
    broker, _, _ = _broker(tmp_path)
    g = TaskGraph("t")
    g.task("n", "N", worker="w", inert=True)
    report = _runner(
        g, {"w": lambda node: {"text": "ok", "cost_usd": 0.0}}, broker
    ).run()
    assert report.ok
