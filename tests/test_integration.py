"""Integration pass (Lane 5): the provenance cut wired into the demo
path, the source-level Gatekeeper wraps, and the package exports.

Covers:
  * the demo crew's artifacts carry no grades — grades enter the run
    from the Judge alone (Council AM-7iii, the eighth seam), and
    Leonardo's expander holds: zero grade-key emissions in the demo path;
  * the demo runner is built with CrewRunner.governed(...) and seals its
    audit log with a signed checkpoint that verifies offline;
  * Gatekeeper.authorize itself is fail-closed at the source (AM-10iii)
    and record-or-halt on audit-write failure (AM-10v) — not only via
    the runner-side wrap.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

import chancellor
from chancellor import cli
from chancellor.api_client import ChatResponse, MetaModelClient
from chancellor.escalation import (
    ActionClass,
    AuditLog,
    AuditWriteError,
    EscalationRequest,
    Gatekeeper,
)
from chancellor.grader import OUTPUT_RUBRIC
from chancellor.instruments import default_panel
from chancellor.judge import Judge
from chancellor.orchestrator import CrewRunner
from chancellor.task_graph import TaskGraph
from chancellor.verify_log import verify_log

# ---------------------------------------------------------------- demo run


def _assert_no_grade_key(obj, where="state"):
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key != "scores", f"grade key emitted at {where}"
            _assert_no_grade_key(value, f"{where}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _assert_no_grade_key(value, f"{where}[{i}]")


def test_demo_crew_artifacts_carry_no_grades(tmp_path):
    """Grep-level half of the expander: the demo path's source never
    puts a grade key on an artifact."""
    source = Path(cli.__file__).read_text(encoding="utf-8")
    assert '"scores"' not in source
    assert "'scores'" not in source


def test_demo_run_grades_come_from_the_judge(tmp_path, capsys):
    """Behavioral half: a full demo run completes with judge-produced
    grades while every persisted artifact is grade-free, and the audit
    log it ships verifies — checkpoint included."""
    state_dir = tmp_path / ".chancellor"
    assert cli.run_demo(str(state_dir)) == 0
    out = capsys.readouterr().out
    # Stranger test S6: the demo's grades are scripted rehearsal grades,
    # and the printed line must say so (was: "by judge, pin").
    assert "scripted offline judge — rehearsal grades, pin" in out

    state = json.loads((state_dir / "demo.state.json").read_text())
    nodes = {n["id"]: n for n in state["nodes"]}
    assert set(nodes) == {"research", "draft", "review"}
    for node in nodes.values():
        assert node["status"] == "done"
        # 87.5 is the demo judge's deterministic grade for these outputs
        # (9/8/8/10 over the OUTPUT_RUBRIC weights) — it can only have
        # come from the judge; the artifacts hold no grades to copy.
        assert node["grade"] == 87.5
        _assert_no_grade_key(node.get("output"), f"output.{node['id']}")

    result = verify_log(state_dir / "audit-log.jsonl", accept_dev_signer=True)
    assert result.ok, result.failures
    assert result.checkpoints == 1


def test_demo_audit_log_verifies_via_module_cli(tmp_path):
    """The shipped demo log passes `python -m chancellor.verify_log` with
    exit 0, exactly as the submission's stranger would run it."""
    state_dir = tmp_path / ".chancellor"
    assert cli.run_demo(str(state_dir)) == 0
    env = dict(os.environ)
    src = str(Path(chancellor.__file__).resolve().parent.parent)
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "chancellor.verify_log",
            str(state_dir / "audit-log.jsonl"),
            "--accept-dev-signer",
        ],
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "VERIFIED" in proc.stdout


# ------------------------------------------------- provenance, unit level

_JUDGE_TABLE = {"correctness": 8.0, "completeness": 6.0, "clarity": 7.0, "safety": 9.0}


def _scripted_judge_transport(model, messages, **kwargs):
    crit = re.search(r"Criterion: (\w+)", messages[-1].content).group(1)
    return ChatResponse(
        text=f"Sound on {crit}.\nSCORE: {_JUDGE_TABLE[crit]}",
        model=model,
        usage={"prompt_tokens": 0, "completion_tokens": 0},
    )


def test_governed_runner_grades_via_score_provider():
    """A graded node whose artifact carries no grades completes on the
    judge's grades when a score provider is wired — and the stored
    artifact stays grade-free."""
    graph = TaskGraph(name="provider-run")
    graph.task("only", "Do the thing", worker="w", inert=True)
    client = MetaModelClient(transport=_scripted_judge_transport)
    judge = Judge(
        client,
        model="muse-wonder-1.0",
        rubric=OUTPUT_RUBRIC,
        worker_model="muse-spark-1.3",
    )
    runner = CrewRunner.governed(
        graph,
        workers={"w": lambda node: {"text": "the work product"}},
        panel=default_panel(),
        rubric=OUTPUT_RUBRIC,
        gatekeeper=Gatekeeper(),
        score_provider=lambda node, artifact: judge.score_proposal(
            node.id, artifact["text"]
        ),
    )
    report = runner.run()
    assert report.ok and report.completed == ["only"]
    # (8*.35 + 6*.25 + 7*.20 + 9*.20) / 10 * 100 = 75.0 — the judge's
    # table, not anything the worker supplied (it supplied nothing).
    assert report.grades == {"only": 75.0}
    stored = graph.nodes["only"].output
    assert stored == {"text": "the work product"}


# ------------------------------------------------ Gatekeeper source wraps


def _send_request():
    return EscalationRequest(
        action="Send the draft", action_class=ActionClass.EXTERNAL_SEND
    )


def test_gatekeeper_approver_exception_denies_with_receipt(tmp_path):
    """AM-10iii at the source: an approver that raises yields a DENY
    Decision from authorize itself, and the denial is receipted."""
    audit = AuditLog(tmp_path / "audit.jsonl")

    def exploding_approver(req):
        raise RuntimeError("approver process died")

    gk = Gatekeeper(audit_log=audit, approver=exploding_approver, human_id="human-1")
    decision = gk.authorize(_send_request())
    assert decision.approved is False
    assert decision.decider == "policy"
    assert "fail-closed" in decision.rationale
    entries = audit.read_all()
    assert len(entries) == 1
    assert entries[0]["approved"] is False
    assert entries[0]["action_class"] == "external_send"


class _BrokenLog:
    """An audit log whose write always fails (disk full, fs gone)."""

    def __init__(self):
        self.attempts = 0

    def record(self, decision):
        self.attempts += 1
        raise OSError("no space left on device")


def test_gatekeeper_audit_write_failure_is_record_or_halt():
    """AM-10v at the source: when the receipt cannot be written, the
    approval does not take effect — authorize raises AuditWriteError
    instead of returning an unrecorded approval."""
    log = _BrokenLog()
    gk = Gatekeeper(
        audit_log=log, approver=lambda req: (True, "looks fine"), human_id="human-1"
    )
    with pytest.raises(AuditWriteError):
        gk.authorize(_send_request())
    assert log.attempts == 1


def test_gatekeeper_audit_write_failure_halts_even_a_denial():
    """Record-or-halt is symmetric: a denial that cannot be receipted
    also halts rather than vanishing silently."""
    gk = Gatekeeper(audit_log=_BrokenLog(), approver=None)
    with pytest.raises(AuditWriteError):
        gk.authorize(_send_request())


def test_gatekeeper_normal_paths_still_receipted(tmp_path):
    audit = AuditLog(tmp_path / "audit.jsonl")
    gk = Gatekeeper(
        audit_log=audit,
        approver=lambda req: (True, "approved in test"),
        human_id="human-1",
    )
    assert gk.authorize(_send_request()).approved is True
    assert (
        gk.authorize(
            EscalationRequest(
                action="Read a file", action_class=ActionClass.READ, tool="read_file"
            )
        ).approved
        is True
    )
    assert len(audit.read_all()) == 2


# ------------------------------------------------------------------ exports


def test_package_level_exports():
    for name in (
        "AttemptCapError",
        "IllegalTransitionError",
        "SCHEMA_VERSION",
        "Judge",
        "JudgeError",
        "CostMeter",
        "AuditLog",
        "AuditWriteError",
    ):
        assert name in chancellor.__all__
        assert getattr(chancellor, name) is not None
    assert chancellor.SCHEMA_VERSION == 1
