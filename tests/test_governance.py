"""Governance by construction + revise semantics + resume behavior.

The production constructor refuses an ungoverned runner at build time;
'revise' means the node goes back for another attempt; a blocked node
re-evaluates only when a decider is actually attached.
"""

import pytest

from chancellor.escalation import Gatekeeper
from chancellor.grader import OUTPUT_RUBRIC
from chancellor.instruments import InstrumentPanel, default_panel
from chancellor.orchestrator import CrewRunner
from chancellor.task_graph import NodeStatus, TaskGraph

GOOD = {"correctness": 9, "completeness": 9, "clarity": 9, "safety": 10}
# 6/10 across the board -> 60.0, squarely in the revise band (50..70).
MEDIOCRE = {"correctness": 6, "completeness": 6, "clarity": 6, "safety": 6}


def _graph():
    g = TaskGraph("t")
    g.task("one", "One", worker="w", inert=True)
    return g


def _ok(node):
    return {"text": "fine", "cost_usd": 0.01, "scores": GOOD}


# -- construction ---------------------------------------------------------------


def test_governed_requires_all_three_layers():
    g, w = _graph(), {"w": _ok}
    panel, gk = default_panel(), Gatekeeper()
    with pytest.raises(ValueError):
        CrewRunner.governed(g, w, panel=None, rubric=OUTPUT_RUBRIC, gatekeeper=gk)
    with pytest.raises(ValueError):
        CrewRunner.governed(g, w, panel=panel, rubric=None, gatekeeper=gk)
    with pytest.raises(ValueError):
        CrewRunner.governed(g, w, panel=panel, rubric=OUTPUT_RUBRIC, gatekeeper=None)


def test_governed_rejects_empty_panel():
    with pytest.raises(ValueError):
        CrewRunner.governed(
            _graph(),
            {"w": _ok},
            panel=InstrumentPanel(),
            rubric=OUTPUT_RUBRIC,
            gatekeeper=Gatekeeper(),
        )


def test_governed_runner_runs_and_reports_governed():
    runner = CrewRunner.governed(
        _graph(),
        {"w": _ok},
        panel=default_panel(),
        rubric=OUTPUT_RUBRIC,
        gatekeeper=Gatekeeper(),
    )
    report = runner.run()
    assert report.ok and report.governed is True


def test_ungoverned_named_path_is_explicit():
    runner = CrewRunner.ungoverned(_graph(), {"w": _ok})
    report = runner.run()
    assert report.ok and report.governed is False


# -- revise means revise ----------------------------------------------------------


def test_revise_requeues_and_second_attempt_can_pass():
    calls = {"n": 0}

    def improving(node):
        calls["n"] += 1
        scores = MEDIOCRE if calls["n"] == 1 else GOOD
        return {"text": f"attempt {calls['n']}", "cost_usd": 0.0, "scores": scores}

    g = _graph()
    report = CrewRunner(g, {"w": improving}, rubric=OUTPUT_RUBRIC).run()
    assert report.ok and report.completed == ["one"]
    assert report.revised == ["one"]
    assert g.nodes["one"].attempts == 2
    assert report.grades["one"] > 70  # final grade is the passing one


def test_revise_exhaustion_fails_the_node():
    def stuck(node):
        return {"text": "same draft", "cost_usd": 0.0, "scores": MEDIOCRE}

    g = TaskGraph("t")
    g.task("one", "One", worker="w", max_attempts=3)
    report = CrewRunner(g, {"w": stuck}, rubric=OUTPUT_RUBRIC).run()
    assert report.halted and report.failed == ["one"]
    assert g.nodes["one"].attempts == 3
    assert g.nodes["one"].status is NodeStatus.FAILED
    assert "revise" in (report.halt_reason or "")
    assert report.revised == ["one", "one"]  # two requeues, third failed


def test_revise_with_cap_one_fails_immediately():
    def stuck(node):
        return {"text": "draft", "cost_usd": 0.0, "scores": MEDIOCRE}

    g = TaskGraph("t")
    g.task("one", "One", worker="w", max_attempts=1)
    report = CrewRunner(g, {"w": stuck}, rubric=OUTPUT_RUBRIC).run()
    assert report.failed == ["one"] and g.nodes["one"].attempts == 1


# -- resume behavior through the runner --------------------------------------------


def _spender_graph():
    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    return g


def _spender(node):
    return {
        "text": "buy it",
        "cost_usd": 5.0,
        "scores": GOOD,
        "action": {"action": "Buy credits", "action_class": "spend", "cost_usd": 5.0},
    }


def test_blocked_node_reevaluates_when_approver_attaches(tmp_path):
    state = tmp_path / "state.json"
    g = _spender_graph()
    runner = CrewRunner(g, {"w": _spender}, gatekeeper=Gatekeeper(), state_path=state)
    report = runner.run()
    assert report.blocked == ["one"]

    # Resume from disk with a decider attached: the gate re-decides.
    g2 = TaskGraph.load(state)
    assert g2.nodes["one"].status is NodeStatus.BLOCKED
    gk = Gatekeeper(approver=lambda req: (True, "approved on resume"))
    report2 = CrewRunner(g2, {"w": _spender}, gatekeeper=gk, state_path=state).run()
    assert report2.ok and report2.completed == ["one"]
    assert "re-evaluation" in report2.dispositions["one"]


def test_blocked_node_stays_blocked_without_approver(tmp_path):
    state = tmp_path / "state.json"
    g = _spender_graph()
    CrewRunner(g, {"w": _spender}, gatekeeper=Gatekeeper(), state_path=state).run()
    g2 = TaskGraph.load(state)
    report = CrewRunner(
        g2, {"w": _spender}, gatekeeper=Gatekeeper(), state_path=state
    ).run()
    assert report.halted and report.completed == []
    assert g2.nodes["one"].status is NodeStatus.BLOCKED
    assert "blocked" in report.dispositions["one"]


def test_runner_resumes_interrupted_node(tmp_path):
    state = tmp_path / "state.json"
    g = TaskGraph("t")
    g.task("one", "One", worker="w")
    g.task("two", "Two", depends_on=["one"], worker="w")
    g.complete("one", output="kept")
    g.start("two")  # dispatched, then "killed"
    g.save(state)

    g2 = TaskGraph.load(state)
    report = CrewRunner(g2, {"w": _ok}, state_path=state).run()
    assert report.ok and report.completed == ["two"]
    assert g2.nodes["one"].output == "kept"  # completed work not re-run
    assert "requeued" in report.dispositions["two"]
