from warden.escalation import ActionClass, EscalationRequest, Gatekeeper
from warden.grader import OUTPUT_RUBRIC
from warden.instruments import CheckResult, InstrumentPanel, default_panel
from warden.orchestrator import CrewRunner
from warden.task_graph import NodeStatus, TaskGraph

GOOD = {"correctness": 9, "completeness": 9, "clarity": 9, "safety": 10}


def _two_node_graph():
    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    g.task("two", "Two", depends_on=["one"], worker="w")
    return g


def _ok_worker(node):
    return {"text": f"output of {node.id}", "cost_usd": 0.01, "scores": GOOD}


def test_full_run_completes(tmp_path):
    runner = CrewRunner(_two_node_graph(), {"w": _ok_worker},
                        panel=default_panel(), rubric=OUTPUT_RUBRIC,
                        state_path=tmp_path / "s.json")
    report = runner.run()
    assert report.ok and report.completed == ["one", "two"]
    assert (tmp_path / "s.json").exists()


def test_instrument_failure_halts_before_downstream():
    calls = []

    def flaky(node):
        calls.append(node.id)
        if node.id == "one":
            return {"text": "", "cost_usd": 0.0, "scores": GOOD}  # empty -> rejected
        return _ok_worker(node)

    runner = CrewRunner(_two_node_graph(), {"w": flaky}, panel=default_panel())
    report = runner.run()
    assert report.halted and report.failed == ["one"]
    assert calls == ["one"]  # downstream never ran


def test_broken_instrument_halts_run():
    def boom(_artifact):
        raise RuntimeError("gauge down")

    panel = InstrumentPanel().register("boom", boom)
    runner = CrewRunner(_two_node_graph(), {"w": _ok_worker}, panel=panel)
    report = runner.run()
    assert report.halted and "instrument error" in (report.halt_reason or "")


def test_failing_grade_rejects_output():
    def weak(node):
        return {"text": "thin", "cost_usd": 0.0,
                "scores": {"correctness": 1, "completeness": 1,
                           "clarity": 1, "safety": 1}}

    runner = CrewRunner(_two_node_graph(), {"w": weak}, rubric=OUTPUT_RUBRIC)
    report = runner.run()
    assert report.halted and report.failed == ["one"]


def test_gate_denial_blocks_node():
    def spender(node):
        artifact = _ok_worker(node)
        artifact["action"] = EscalationRequest(
            action="Buy inference credits", action_class=ActionClass.SPEND,
            cost_usd=25.0, node_id=node.id)
        return artifact

    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    runner = CrewRunner(g, {"w": spender}, gatekeeper=Gatekeeper())  # no approver
    report = runner.run()
    assert report.halted and report.blocked == ["one"]
    assert g.nodes["one"].status is NodeStatus.BLOCKED
