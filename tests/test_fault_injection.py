"""T2 fault-injection tests — the fail-closed claim, proven under attack.

Every injected failure must produce the same shape: the run halts, zero
outputs are accepted from the failed node, downstream never executes,
and nothing raises out of the runner.
"""
import time

from warden.escalation import ActionClass, AuditLog, Gatekeeper
from warden.grader import OUTPUT_RUBRIC
from warden.instruments import InstrumentPanel, default_panel
from warden.orchestrator import CrewRunner
from warden.task_graph import NodeStatus, TaskGraph

GOOD = {"correctness": 9, "completeness": 9, "clarity": 9, "safety": 10}


def _graph():
    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    g.task("two", "Two", depends_on=["one"], worker="w")
    return g


def _ok(node):
    return {"text": f"output of {node.id}", "cost_usd": 0.01, "scores": GOOD}


# -- instruments under attack --------------------------------------------------

def test_instrument_error_halts_with_zero_accepted():
    def boom(_artifact):
        raise RuntimeError("gauge down")

    panel = InstrumentPanel().register("boom", boom)
    calls = []

    def worker(node):
        calls.append(node.id)
        return _ok(node)

    report = CrewRunner(_graph(), {"w": worker}, panel=panel).run()
    assert report.halted and report.completed == []
    assert calls == ["one"]  # downstream never ran
    assert "boom" in (report.halt_reason or "")


def test_instrument_garbage_return_halts():
    for garbage in (42, "yes", None, 3.14, object()):
        panel = InstrumentPanel().register("junk", lambda _a, g=garbage: g)
        report = CrewRunner(_graph(), {"w": _ok}, panel=panel).run()
        assert report.halted and report.completed == []
        assert "garbage" in (report.halt_reason or "")


def test_instrument_timeout_is_a_deny_not_a_hang():
    def slow(_artifact):
        time.sleep(1.0)
        return True

    panel = InstrumentPanel(timeout_s=0.2).register("slow", slow)
    started = time.monotonic()
    report = CrewRunner(_graph(), {"w": _ok}, panel=panel).run()
    elapsed = time.monotonic() - started
    assert report.halted and report.completed == []
    assert "timed out" in (report.halt_reason or "")
    assert elapsed < 0.9  # the run denied promptly instead of hanging


def test_empty_panel_never_reports_ok():
    result = InstrumentPanel().run_all({"text": "anything"})
    assert not result.ok
    assert "empty" in result.halt_reason


# -- grader under attack ---------------------------------------------------------

def _run_with_scores(scores):
    def worker(node):
        return {"text": "x", "cost_usd": 0.0, "scores": scores}

    return CrewRunner(_graph(), {"w": worker}, rubric=OUTPUT_RUBRIC).run()


def test_grader_error_mid_run_halts_with_zero_accepted():
    poisoned = [dict(GOOD, correctness=float("nan")),
                dict(GOOD, safety=float("inf")),
                {k: v for k, v in GOOD.items() if k != "clarity"},
                "not-a-dict",
                dict(GOOD, clarity="high"),
                dict(GOOD, safety=None)]
    for scores in poisoned:
        report = _run_with_scores(scores)
        assert report.halted and report.completed == []
        assert report.failed == ["one"]


def test_scores_less_artifact_on_graded_node_halts():
    def worker(node):
        return {"text": "ungraded but confident", "cost_usd": 0.0}

    report = CrewRunner(_graph(), {"w": worker}, rubric=OUTPUT_RUBRIC).run()
    assert report.halted and report.completed == []
    assert "no scores" in (report.halt_reason or "")


def test_declared_ungraded_node_completes_without_scores():
    g = TaskGraph("t")
    g.task("one", "One", worker="w", requires_grade=False)

    def worker(node):
        return {"text": "side-effect only", "cost_usd": 0.0}

    report = CrewRunner(g, {"w": worker}, rubric=OUTPUT_RUBRIC).run()
    assert report.ok and report.completed == ["one"]
    assert report.grades == {}


# -- gates under attack ------------------------------------------------------------

def _gated_worker(action):
    def worker(node):
        artifact = _ok(node)
        artifact["action"] = action
        return artifact

    return worker


def test_gate_actions_never_auto(tmp_path):
    """Fuzz every action class: human-gate classes block with exactly
    one receipt and zero executions; policy classes complete."""
    human = {ActionClass.SPEND, ActionClass.EXTERNAL_SEND,
             ActionClass.PUBLISH, ActionClass.IRREVERSIBLE,
             ActionClass.CREDENTIAL}
    for cls in ActionClass:
        log = AuditLog(tmp_path / f"audit-{cls.value}.jsonl")
        g = TaskGraph("t")
        g.task("one", "One", worker="w")
        action = {"action": f"do {cls.value}", "action_class": cls.value,
                  "cost_usd": 1.0}
        runner = CrewRunner(g, {"w": _gated_worker(action)},
                            gatekeeper=Gatekeeper(audit_log=log))
        report = runner.run()
        entries = log.read_all()
        assert len(entries) == 1, cls
        if cls in human:
            assert report.blocked == ["one"] and report.completed == []
            assert entries[0]["approved"] is False
        else:
            assert report.completed == ["one"]
            assert entries[0]["approved"] is True


def test_gate_class_string_coerced_and_validated():
    # Case/whitespace drift in model output must still hit the human gate.
    for drifted in ("SPEND", "Spend", " spend "):
        g = TaskGraph("t")
        g.task("one", "One", worker="w")
        action = {"action": "buy", "action_class": drifted, "cost_usd": 5.0}
        report = CrewRunner(g, {"w": _gated_worker(action)},
                            gatekeeper=Gatekeeper()).run()
        assert report.blocked == ["one"], drifted
        assert g.nodes["one"].status is NodeStatus.BLOCKED
    # An auto class as a raw string coerces and passes by policy.
    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    action = {"action": "compute", "action_class": "compute"}
    report = CrewRunner(g, {"w": _gated_worker(action)},
                        gatekeeper=Gatekeeper()).run()
    assert report.completed == ["one"]


def test_malformed_gate_requests_halt_never_crash():
    bad_actions = [
        {"action": "x", "action_class": "bogus-class"},
        {"action": "x"},                                # missing class
        {"surprise": True},                             # wrong keys entirely
        42,                                             # not a mapping
        "spend please",                                 # not a mapping
        {"action": "x", "action_class": 7},             # wrong type
    ]
    for bad in bad_actions:
        g = TaskGraph("t")
        g.task("one", "One", worker="w")
        report = CrewRunner(g, {"w": _gated_worker(bad)},
                            gatekeeper=Gatekeeper()).run()
        assert report.halted and report.completed == [], bad
        assert report.failed == ["one"], bad


def test_approver_that_raises_is_a_denial_not_a_crash(tmp_path):
    def angry(_req):
        raise RuntimeError("approver unreachable")

    log = AuditLog(tmp_path / "audit.jsonl")
    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    action = {"action": "buy", "action_class": "spend", "cost_usd": 5.0}
    gk = Gatekeeper(audit_log=log, approver=angry)
    report = CrewRunner(g, {"w": _gated_worker(action)}, gatekeeper=gk).run()
    assert report.halted and report.blocked == ["one"]
    assert report.completed == []
    assert g.nodes["one"].status is NodeStatus.BLOCKED


def test_audit_log_is_append_only_by_prefix(tmp_path):
    """Snapshot bytes after each decision: every earlier snapshot is a
    strict prefix of the later file — the log is never rewritten."""
    from warden.escalation import EscalationRequest

    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    gk = Gatekeeper(audit_log=log)
    snapshots = []
    for i in range(5):
        gk.authorize(EscalationRequest(
            action=f"decision {i}", action_class=ActionClass.SPEND))
        snapshots.append(path.read_bytes())
    for earlier, later in zip(snapshots, snapshots[1:]):
        assert later.startswith(earlier) and len(later) > len(earlier)
    assert len(log.read_all()) == 5
