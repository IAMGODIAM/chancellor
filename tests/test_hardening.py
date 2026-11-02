"""Hardening tests: signer labelling, operator-supplied supervise key,
policy-table classification, fail-closed classification, per-node
receipts, automatic checkpoints, stamped payloads, strict arguments, and
the interception layer with its reconcile step."""

import contextlib
import json
import time
from pathlib import Path

import pytest

from chancellor import receipts
from chancellor.cli import main as cli_main
from chancellor.escalation import (
    DEFAULT_CHECKPOINT_EVERY,
    REFUSAL_NO_APPROVER,
    REFUSAL_NODE_FAILED,
    REFUSAL_RECONCILE_MISMATCH,
    REFUSAL_UNCLASSIFIED,
    ActionClass,
    ActionPolicy,
    AuditLog,
    Decision,
    EscalationRequest,
    Gatekeeper,
)
from chancellor.evals.suite_b import check_payload_integrity
from chancellor.evals.suite_b_world import checksum_of
from chancellor.grader import OUTPUT_RUBRIC
from chancellor.instruments import default_panel
from chancellor.interception import InterceptRecord, ToolBroker, ToolDenied
from chancellor.orchestrator import CrewRunner
from chancellor.task_graph import TaskGraph
from chancellor.verify_log import DEV_SIGNER_LABEL, verify_log
from chancellor.verify_log import main as verify_main

GOOD = {"correctness": 9, "completeness": 9, "clarity": 9, "safety": 10}
THROWAWAY_KEY = "throwaway-test-value-not-a-real-key"


# ------------------------------------------------------------ helpers
def _seed(path: Path, n: int = 3, **kwargs) -> AuditLog:
    log = AuditLog(path, **kwargs)
    for i in range(n):
        req = EscalationRequest(
            action="segment", action_class=ActionClass.COMPUTE, detail=str(i)
        )
        log.record(Decision(req, True, "agent", "ok", time.time()))
    return log


def _runner(graph, workers, gatekeeper, broker=None):
    return CrewRunner.governed(
        graph,
        workers,
        panel=default_panel(),
        rubric=OUTPUT_RUBRIC,
        gatekeeper=gatekeeper,
        broker=broker,
        score_provider=lambda node, artifact: GOOD,
    )


def _one_node(worker, *, inert=False):
    g = TaskGraph("t")
    g.task("n", "N", worker="w", inert=inert)
    return g, {"w": worker}


def _artifact(action):
    return lambda node: {"text": "work done", "cost_usd": 0.0, "action": action}


# ------------------------------------------------- 1. signer labelling
def test_verify_log_labels_dev_signer_and_requires_acceptance(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    _seed(path).checkpoint()

    assert verify_main([str(path)]) == 1
    out = capsys.readouterr().out
    assert DEV_SIGNER_LABEL in out
    assert "dev_signer_not_accepted" in out

    assert verify_main([str(path), "--accept-dev-signer"]) == 0
    out = capsys.readouterr().out
    assert DEV_SIGNER_LABEL in out
    assert "VERIFIED" in out


def test_verify_log_result_flags_dev_signer(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path).checkpoint()
    refused = verify_log(path)
    assert not refused.ok and refused.dev_signer
    accepted = verify_log(path, accept_dev_signer=True)
    assert accepted.ok and accepted.dev_signer


class _OtherSigner:
    key_id = "operator-signer-test"

    def sign(self, data: bytes) -> bytes:
        return receipts.DevHmacSigner(secret=b"other").sign(data)

    def verify(self, data: bytes, sig: bytes) -> bool:
        return self.sign(data) == sig


def test_verify_log_non_dev_signer_needs_no_flag(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed(path, signer=_OtherSigner()).checkpoint()
    result = verify_log(path, signer=_OtherSigner())
    assert result.ok and not result.dev_signer


# ------------------------------------------- 2. supervise needs a key
def test_supervise_refuses_without_operator_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("CHANCELLOR_SUPERVISE_KEY", raising=False)
    state = tmp_path / "state"
    rc = cli_main(["supervise", "--state-dir", str(state), "--", "true"])
    assert rc == 2
    assert "operator signing key" in capsys.readouterr().err
    assert not state.exists()


@pytest.mark.parametrize("bad", ["", "   ", receipts.DEV_SIGNER_SECRET.decode()])
def test_supervise_refuses_unusable_key(tmp_path, monkeypatch, bad, capsys):
    monkeypatch.setenv("CHANCELLOR_SUPERVISE_KEY", bad)
    rc = cli_main(["supervise", "--state-dir", str(tmp_path / "s"), "--", "true"])
    assert rc == 2
    assert "refusing to run" in capsys.readouterr().err


@pytest.mark.parametrize("via", ["env", "option"])
def test_supervise_takes_key_from_env_or_option(tmp_path, monkeypatch, via):
    seen = {}

    class _Stub:
        def __init__(self, config, *, signer, launcher):
            seen["secret"] = signer._secret

        def run(self):
            return 0

    monkeypatch.delenv("CHANCELLOR_SUPERVISE_KEY", raising=False)
    monkeypatch.setattr("chancellor.cli.Supervisor", _Stub)
    args = ["supervise", "--state-dir", str(tmp_path / "s")]
    if via == "env":
        monkeypatch.setenv("CHANCELLOR_SUPERVISE_KEY", THROWAWAY_KEY)
    else:
        args += ["--signing-key", THROWAWAY_KEY]
    assert cli_main([*args, "--", "true"]) == 0
    assert seen["secret"] == THROWAWAY_KEY.encode()


# ------------------------------------- 3. policy table decides class
def test_policy_table_sets_class_from_tool():
    policy = ActionPolicy()
    cls = policy.classify(EscalationRequest(action="x", tool="wire_transfer"))
    assert cls.action_class is ActionClass.SPEND and cls.denied_reason is None


def test_policy_table_sets_class_from_effect():
    policy = ActionPolicy()
    req = EscalationRequest(action="x", effects=("external_visibility",))
    assert policy.classify(req).action_class is ActionClass.EXTERNAL_SEND


def test_declared_class_never_loosens_the_table():
    policy = ActionPolicy()
    looser = EscalationRequest(
        action="x", action_class=ActionClass.COMPUTE, tool="wire_transfer"
    )
    assert policy.classify(looser).action_class is ActionClass.SPEND
    drifted = EscalationRequest(action="x", action_class=" Read ", tool="send_email")
    assert policy.classify(drifted).action_class is ActionClass.EXTERNAL_SEND


def test_declared_class_can_tighten_the_table():
    policy = ActionPolicy()
    stricter = EscalationRequest(
        action="x", action_class=ActionClass.IRREVERSIBLE, tool="read_file"
    )
    assert policy.classify(stricter).action_class is ActionClass.IRREVERSIBLE


def test_runner_gates_by_table_when_worker_declares_looser_class(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    action = {"action": "pay", "action_class": "compute", "tool": "wire_transfer"}
    g, w = _one_node(_artifact(action))
    report = _runner(g, w, Gatekeeper(audit_log=log)).run()
    assert report.halted and report.blocked == ["n"]
    entry = log.read_all()[0]
    assert entry["action_class"] == "spend"
    assert entry["declared_class"] == "compute"
    assert entry["approved"] is False


def test_no_approver_denies_every_non_compute_class(tmp_path):
    tools = {
        "send_email": "external_send",
        "wire_transfer": "spend",
        "publish_post": "publish",
        "delete_file": "irreversible",
        "use_credential": "credential",
    }
    for tool, expected in tools.items():
        log = AuditLog(tmp_path / f"{tool}.jsonl")
        decision = Gatekeeper(audit_log=log).authorize(
            EscalationRequest(action="x", tool=tool)
        )
        assert not decision.approved
        assert decision.refusal_state == REFUSAL_NO_APPROVER
        assert log.read_all()[0]["action_class"] == expected
    assert (
        Gatekeeper().authorize(EscalationRequest(action="x", tool="compute")).approved
    )


# --------------------------------------- 4. unclassified is denied
@pytest.mark.parametrize(
    "request_",
    [
        EscalationRequest(action="x"),  # nothing declared
        EscalationRequest(action="x", tool="no_such_tool"),
        EscalationRequest(action="x", action_class="bogus"),
        EscalationRequest(action="x", action_class=7),  # type: ignore[arg-type]
        EscalationRequest(action="x", action_class=ActionClass.COMPUTE),
        EscalationRequest(action="x", action_class=ActionClass.UNCLASSIFIED),
        EscalationRequest(action="x", effects=("no_such_effect",)),
    ],
)
def test_unclassified_request_is_denied_with_receipt(tmp_path, request_):
    log = AuditLog(tmp_path / "a.jsonl")
    seen = []
    gk = Gatekeeper(audit_log=log, approver=lambda r: (seen.append(r), (True, "ok"))[1])
    decision = gk.authorize(request_)
    assert not decision.approved
    assert decision.refusal_state == REFUSAL_UNCLASSIFIED
    assert seen == []  # never reaches the approver
    assert log.read_all()[0]["action_class"] == "unclassified"


def test_missing_action_key_is_denied_with_receipt(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    g, w = _one_node(lambda node: {"text": "done", "cost_usd": 0.0})
    report = _runner(g, w, Gatekeeper(audit_log=log)).run()
    assert report.halted and report.blocked == ["n"] and not report.completed
    [entry] = log.read_all()
    assert entry["approved"] is False
    assert entry["refusal_state"] == REFUSAL_UNCLASSIFIED


# ------------------------------------------------ 5. every node receipted
def test_every_node_gets_a_receipt(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    g = TaskGraph("t")
    g.task("a", "A", worker="plain", inert=True)
    g.task("b", "B", depends_on=["a"], worker="acts")
    g.task("c", "C", depends_on=["b"], worker="plain", inert=True)
    workers = {
        "plain": lambda node: {"text": "ok", "cost_usd": 0.0},
        "acts": _artifact({"action": "read", "tool": "read_file"}),
    }
    report = _runner(g, workers, Gatekeeper(audit_log=log)).run()
    assert report.ok and report.completed == ["a", "b", "c"]
    entries = log.read_all()
    assert [e["node_id"] for e in entries] == ["a", "b", "c"]
    assert "no action declared" in entries[0]["action"]
    assert all(e["approved"] for e in entries)


def test_failed_node_leaves_a_receipt(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")

    def broken(node):
        raise RuntimeError("worker down")

    g, w = _one_node(broken)
    report = _runner(g, w, Gatekeeper(audit_log=log)).run()
    assert report.failed == ["n"]
    [entry] = log.read_all()
    assert entry["approved"] is False and entry["refusal_state"] == REFUSAL_NODE_FAILED


def test_malformed_action_leaves_a_receipt(tmp_path):
    log = AuditLog(tmp_path / "a.jsonl")
    g, w = _one_node(_artifact({"surprise": True}))
    report = _runner(g, w, Gatekeeper(audit_log=log)).run()
    assert report.halted and not report.completed
    [entry] = log.read_all()
    assert entry["approved"] is False


# --------------------------------------------- 6. automatic checkpoints
def test_log_seals_itself_every_n_entries(tmp_path):
    log = _seed(tmp_path / "a.jsonl", n=7, checkpoint_every=3)
    sealed = [
        receipts.checkpoint_payload(json.loads(line))["log_size"]
        for line in log.checkpoint_path.read_text().splitlines()
    ]
    assert sealed == [3, 6]
    # Entries past the newest seal are named by length.
    result = verify_log(log.path, accept_dev_signer=True)
    assert not result.ok
    assert any("unsealed tail: 1 entries" in f for f in result.failures)
    log.checkpoint()
    assert verify_log(log.path, accept_dev_signer=True).ok


def test_default_seal_interval_is_sensible_and_validated(tmp_path):
    assert 1 <= DEFAULT_CHECKPOINT_EVERY <= 64
    log = _seed(tmp_path / "a.jsonl", n=DEFAULT_CHECKPOINT_EVERY)
    assert verify_log(log.path, accept_dev_signer=True).ok  # sealed, no manual call
    with pytest.raises(ValueError):
        AuditLog(tmp_path / "b.jsonl", checkpoint_every=0)
    off = _seed(tmp_path / "c.jsonl", n=DEFAULT_CHECKPOINT_EVERY, checkpoint_every=None)
    assert not off.checkpoint_path.exists()


# ----------------------------------------------- 7. stamped payloads
def test_unstamped_payload_fails_integrity_check():
    assert not check_payload_integrity({"data": {"value": 5}}).ok
    assert not check_payload_integrity({"data": {"value": 5, "checksum": None}}).ok
    assert not check_payload_integrity({"data": {"checksum": "abc"}}).ok


def test_stamped_and_non_tool_payloads_pass_integrity_check():
    stamped = {"data": {"value": 5, "checksum": checksum_of(5)}}
    assert check_payload_integrity(stamped).ok
    assert not check_payload_integrity(
        {"data": {"value": 6, "checksum": checksum_of(5)}}
    ).ok
    assert check_payload_integrity({"data": {"key": "k", "value": 1}}).ok
    assert check_payload_integrity({"data": {"skipped": True}}).ok
    assert check_payload_integrity({"text": "no data"}).ok


def _rechain(path: Path, rows: list[dict]) -> None:
    prev = None
    out = []
    for row in rows:
        row = {k: v for k, v in row.items() if k != "entry_hash"}
        row["prev_hash"] = prev
        row["entry_hash"] = receipts.entry_hash(row)
        prev = row["entry_hash"]
        out.append(row)
    path.write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
    cp = receipts.build_checkpoint(
        signer=receipts.default_signer(),
        log_size=len(out),
        leaves=[r["entry_hash"] for r in out],
        head_hash=prev,
    )
    receipts.default_checkpoint_path(path).write_text(json.dumps(cp) + "\n")


def test_entries_without_frame_stamp_fail_verification(tmp_path):
    path = tmp_path / "a.jsonl"
    _seed(path, n=3).checkpoint()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    del rows[1]["schema"]
    _rechain(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("frame_fields_missing: seq 1") for f in result.failures)


def test_receipt_schema_cannot_step_back_after_frame_era(tmp_path):
    path = tmp_path / "a.jsonl"
    _seed(path, n=3).checkpoint()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[2]["schema"] = receipts.SCHEMA_V1
    _rechain(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("schema_downgrade: seq 2") for f in result.failures)


# ------------------------------------------------ 8. strict arguments
@pytest.mark.parametrize(
    "argv",
    [
        ["eval-a", "--bogus"],
        ["eval-b", "extra"],
        ["demo", "--bogus"],
        ["demo", "extra"],
        ["demo", "--classic", "--fast"],
        ["demo", "--seed"],
        ["demo", "--seed", "x"],
        ["supervise", "--bogus", "--", "true"],
        ["no-such-command"],
    ],
)
def test_unknown_arguments_are_rejected(argv, capsys):
    assert cli_main(argv) == 2
    assert capsys.readouterr().err


def test_eval_help_does_not_run_the_suite(capsys):
    assert cli_main(["eval-a", "--help"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: chancellor eval-a")


def test_verify_log_rejects_unknown_flags(tmp_path):
    with pytest.raises(SystemExit) as exc:
        verify_main([str(tmp_path / "x.jsonl"), "--bogus"])
    assert exc.value.code == 2
    with pytest.raises(SystemExit) as exc:
        verify_main(["resolve", str(tmp_path / "x.jsonl"), "ab" * 32, "--bogus"])
    assert exc.value.code == 2


# --------------------------- 9. interception layer and reconcile
def _broker(tmp_path, approver=None):
    log = AuditLog(tmp_path / "a.jsonl")
    gk = Gatekeeper(audit_log=log, approver=approver)
    ran: list[dict] = []
    broker = ToolBroker(gk)
    broker.register("wire_transfer", lambda **kw: ran.append(kw) or {"ok": True})
    return broker, log, ran


def test_gated_tool_is_checked_before_it_executes(tmp_path):
    broker, log, ran = _broker(tmp_path)  # no approver attached
    with pytest.raises(ToolDenied):
        broker.call("n", "wire_transfer", {"amount": 5})
    assert ran == []
    [entry] = log.read_all()
    assert entry["approved"] is False and entry["action_class"] == "spend"
    assert entry["args_sha256"]


def test_approved_tool_runs_with_the_approved_arguments(tmp_path):
    broker, log, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))
    assert broker.call("n", "wire_transfer", {"amount": 5}) == {"ok": True}
    assert ran == [{"amount": 5}]
    [record] = broker.ledger
    assert record.approved_args_sha256 == record.executed_args_sha256
    assert record.result_sha256
    assert broker.reconcile("n", 0) == []


def test_unregistered_tool_is_denied_with_receipt(tmp_path):
    broker, log, _ = _broker(tmp_path, approver=lambda r: (True, "ok"))
    with pytest.raises(ToolDenied):
        broker.call("n", "send_email", {"to": "x"})
    assert log.read_all()[0]["approved"] is False


def test_arguments_changed_after_approval_do_not_run(tmp_path):
    shared = {"items": [1]}

    def approver(request):
        shared["items"].append(2)  # changes between approval and execution
        return True, "ok"

    broker, log, ran = _broker(tmp_path, approver=approver)
    with pytest.raises(ToolDenied):
        broker.call("n", "wire_transfer", shared)
    assert ran == []
    assert broker.reconcile("n", 0)  # the disagreement is reported


def test_reconcile_names_every_kind_of_disagreement(tmp_path):
    broker, _, _ = _broker(tmp_path)
    broker.ledger += [
        InterceptRecord(
            "n", "wire_transfer", "spend", "aa", approved=False, started=True
        ),
        InterceptRecord(
            "n",
            "wire_transfer",
            "spend",
            "aa",
            approved=True,
            started=True,
            executed_args_sha256="bb",
        ),
    ]
    found = broker.reconcile("n", 0)
    assert any("without approval" in m for m in found)
    assert any("not approved" in m for m in found)
    declared = EscalationRequest(action="x", tool="wire_transfer")
    assert any("declared" in m for m in broker.reconcile("other", 0, declared))


def test_runner_completes_when_ledger_and_declaration_agree(tmp_path):
    broker, log, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))

    def worker(node):
        broker.call(node.id, "wire_transfer", {"amount": 5})
        return {
            "text": "paid",
            "cost_usd": 0.0,
            "action": {"action": "pay", "tool": "wire_transfer"},
        }

    g, w = _one_node(worker)
    report = _runner(g, w, broker.gatekeeper, broker).run()
    assert report.ok and report.completed == ["n"]
    assert len(ran) == 1
    assert len(log.read_all()) == 1  # checked once, before it ran


def test_runner_halts_when_declared_action_never_went_through_broker(tmp_path):
    broker, log, ran = _broker(tmp_path, approver=lambda r: (True, "ok"))
    action = {"action": "pay", "tool": "wire_transfer"}
    g, w = _one_node(_artifact(action))
    report = _runner(g, w, broker.gatekeeper, broker).run()
    assert report.halted and report.failed == ["n"] and not report.completed
    assert ran == []
    assert log.read_all()[-1]["refusal_state"] == REFUSAL_RECONCILE_MISMATCH


def test_runner_halts_when_brokered_call_was_denied_but_declared(tmp_path):
    broker, log, ran = _broker(tmp_path)  # no approver: the call is refused

    def worker(node):
        with contextlib.suppress(ToolDenied):
            broker.call(node.id, "wire_transfer", {"amount": 5})
        return {
            "text": "paid",
            "cost_usd": 0.0,
            "action": {"action": "pay", "tool": "wire_transfer"},
        }

    g, w = _one_node(worker)
    report = _runner(g, w, broker.gatekeeper, broker).run()
    assert report.halted and not report.completed
    assert ran == []
