"""Supervisor key handling: a signer is required; the operator key stays
with the supervisor (never in the agent's environment, nor readable from
the supervisor's /proc entries); the agent gets a sign-only channel that
only signs a true description of its own log; short keys are refused."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
from pinning import OPERATOR_SECRET, operator_signer

import chancellor
from chancellor import receipts
from chancellor.cli import main as cli_main
from chancellor.escalation import (
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
)
from chancellor.sealing import SealService, agent_environment
from chancellor.supervise import SignerRequiredError, Supervisor, SupervisorConfig
from chancellor.verify_log import verify_log

SRC = str(Path(chancellor.__file__).resolve().parent.parent)


def _decision(i: int) -> Decision:
    request = EscalationRequest(
        action="segment", action_class=ActionClass.COMPUTE, detail=str(i)
    )
    return Decision(request, True, "agent", "ok", time.time())


# ------------------------------------------------ signer is required
def test_supervisor_without_a_signer_is_refused(tmp_path):
    config = SupervisorConfig(agent_command=["true"], state_dir=tmp_path)
    with pytest.raises(SignerRequiredError):
        Supervisor(config)
    assert issubclass(SignerRequiredError, ValueError)


def test_dev_signer_must_be_asked_for_by_name(tmp_path):
    config = SupervisorConfig(agent_command=["true"], state_dir=tmp_path)
    sup = Supervisor.with_dev_signer(config)
    assert receipts.is_dev_signer(sup._signer)


def test_boundary_verification_labels_the_dev_signer(tmp_path):
    from chancellor.supervise import verify_at_checkpoint_boundary

    log = AuditLog(tmp_path / "a.jsonl", checkpoint_every=None)
    log.record(_decision(0))
    log.checkpoint_v2()
    result = verify_at_checkpoint_boundary(log.path)
    assert result.ok
    assert any(receipts.DEV_SIGNED_LABEL in w for w in result.warnings)
    quiet = verify_at_checkpoint_boundary(
        AuditLog(
            tmp_path / "b.jsonl", signer=operator_signer(), checkpoint_every=None
        ).path
    )
    assert not quiet.ok  # no log at all: nothing to resume from


def test_boundary_verification_reads_v2_checkpoints(tmp_path):
    from chancellor.supervise import verify_at_checkpoint_boundary

    log = AuditLog(tmp_path / "a.jsonl", signer=operator_signer(), checkpoint_every=2)
    for i in range(4):
        log.record(_decision(i))
    result = verify_at_checkpoint_boundary(log.path, signer=operator_signer())
    assert result.ok and result.log_size == 4
    assert not result.warnings


# ---------------------------------------------------- key strength
@pytest.mark.parametrize("short", ["a", "x" * 31, "0123456789abcdef"])
def test_short_operator_key_is_refused(tmp_path, monkeypatch, short, capsys):
    monkeypatch.setenv("CHANCELLOR_SUPERVISE_KEY", short)
    rc = cli_main(["supervise", "--state-dir", str(tmp_path / "s"), "--", "true"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "shorter than" in err
    assert len(short) < 4 or short not in err


def test_key_is_removed_from_the_process_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("CHANCELLOR_SUPERVISE_KEY", OPERATOR_SECRET)
    monkeypatch.setenv("CHANCELLOR_DEV_SIGNER_SECRET", "another-throwaway-value")
    seen = {}

    class _Stub:
        def __init__(self, config, *, signer, launcher):
            seen["env"] = dict(os.environ)
            seen["signer"] = signer

        def run(self):
            return 0

    monkeypatch.setattr("chancellor.cli.Supervisor", _Stub)
    assert cli_main(["supervise", "--state-dir", str(tmp_path), "--", "true"]) == 0
    assert "CHANCELLOR_SUPERVISE_KEY" not in seen["env"]
    assert "CHANCELLOR_DEV_SIGNER_SECRET" not in seen["env"]
    assert seen["signer"].key_id == operator_signer().key_id


def test_agent_environment_drops_every_key_carrier(monkeypatch):
    for name in (
        "CHANCELLOR_SUPERVISE_KEY",
        "CHANCELLOR_DEV_SIGNER_SECRET",
        receipts.VERIFY_KEY_ENV,
    ):
        monkeypatch.setenv(name, "throwaway-value")
    monkeypatch.setenv("PATH_LIKE", "kept")
    env = agent_environment()
    assert "PATH_LIKE" in env
    assert not {
        "CHANCELLOR_SUPERVISE_KEY",
        "CHANCELLOR_DEV_SIGNER_SECRET",
        receipts.VERIFY_KEY_ENV,
    } & set(env)


# ----------------------------------------------------- sealing service
def _service(tmp_path, n=3):
    log = AuditLog(
        tmp_path / "agent.jsonl", signer=operator_signer(), checkpoint_every=None
    )
    for i in range(n):
        log.record(_decision(i))
    service = SealService(operator_signer(), log.path, log.checkpoint_path)
    return log, service


def _request(log, schema_v2=True, **overrides):
    leaves = [e["entry_hash"] for e in log.read_all()]
    payload = {
        "schema": receipts.CHECKPOINT_SCHEMA_V2
        if schema_v2
        else receipts.CHECKPOINT_SCHEMA,
        "issuer": operator_signer().key_id,
        "created_at": 0,
        "log_size": len(leaves),
        "merkle_root": receipts.rfc9162_root(leaves)
        if schema_v2
        else receipts.merkle_root(leaves),
        "head_receipt_hash": leaves[-1] if leaves else None,
    }
    if schema_v2:
        payload["tree"] = receipts.TREE_RFC9162
    payload.update(overrides)
    payload_type = (
        receipts.CHECKPOINT_PAYLOAD_TYPE_V2
        if schema_v2
        else receipts.CHECKPOINT_PAYLOAD_TYPE
    )
    return receipts.pae(payload_type, receipts.canonical(payload))


def test_service_signs_a_true_checkpoint(tmp_path):
    log, service = _service(tmp_path)
    sig = service.sign_request(_request(log))
    assert operator_signer().verify(_request(log), sig)
    log.record(_decision(3))
    assert service.sign_request(_request(log, schema_v2=False))


@pytest.mark.parametrize(
    "overrides",
    [
        {"merkle_root": "00" * 32},
        {"head_receipt_hash": "00" * 32},
        {"log_size": 99},
        {"issuer": "someone-else"},
        {"schema": "other"},
    ],
)
def test_service_refuses_a_checkpoint_that_misdescribes_the_log(tmp_path, overrides):
    log, service = _service(tmp_path)
    with pytest.raises(receipts.SigningRefused):
        service.sign_request(_request(log, **overrides))


def test_service_refuses_arbitrary_bytes(tmp_path):
    _, service = _service(tmp_path)
    for junk in (b"anything", b"DSSEv1 3 abc 3 xyz", b""):
        with pytest.raises(receipts.SigningRefused):
            service.sign_request(junk)


def test_service_refuses_to_seal_a_rewritten_past(tmp_path):
    log, service = _service(tmp_path)
    service.sign_request(_request(log))
    rows = log.read_all()
    rows[0]["rationale"] = "changed"
    prev = None
    for row in rows:
        row["prev_hash"] = prev
        row["entry_hash"] = receipts.entry_hash(row)
        prev = row["entry_hash"]
    log.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(receipts.SigningRefused) as err:
        service.sign_request(_request(log))
    assert "already sealed" in str(err.value)


def test_service_refuses_to_shrink_sealed_history(tmp_path):
    log, service = _service(tmp_path)
    service.sign_request(_request(log))
    shorter = _request(log, log_size=2)
    with pytest.raises(receipts.SigningRefused):
        service.sign_request(shorter)


def test_service_refuses_a_broken_chain(tmp_path):
    log, service = _service(tmp_path)
    rows = log.read_all()
    rows[1]["rationale"] = "edited without re-chaining"
    log.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    with pytest.raises(receipts.SigningRefused):
        service.sign_request(_request(log))


def test_service_remembers_its_last_seal_across_a_restart(tmp_path):
    log, service = _service(tmp_path)
    envelope = log.checkpoint_v2()
    del envelope
    fresh = SealService(operator_signer(), log.path, log.checkpoint_path)
    with pytest.raises(receipts.SigningRefused):
        fresh.sign_request(_request(log, log_size=1))


def test_agent_signs_through_the_channel_without_the_key(tmp_path, monkeypatch):
    log, service = _service(tmp_path, n=0)
    theirs = service.open_channel()
    monkeypatch.setenv(receipts.SIGN_FD_ENV, str(os.dup(theirs.fileno())))
    theirs.close()
    signer = receipts.default_signer()
    assert isinstance(signer, receipts.PipeSigner)
    assert signer.key_id == operator_signer().key_id
    agent_log = AuditLog(log.path, signer=signer, checkpoint_every=2)
    for i in range(4):
        agent_log.record(_decision(i))
    assert not hasattr(signer, "_secret")
    result = verify_log(log.path, signer=operator_signer())
    assert result.ok and result.authentic
    with pytest.raises(receipts.SigningRefused):
        signer.sign(b"not a checkpoint")
    assert signer.verify(b"x", b"y") is False
    service.close()


# ----------------------------------------- the real command line, end to end
AGENT = r"""
import json, os, sys, time
from pathlib import Path
from chancellor import receipts
from chancellor.escalation import ActionClass, AuditLog, Decision, EscalationRequest

key = Path(sys.argv[1]).read_text()
report_path = Path(sys.argv[2])
log_path = Path(sys.argv[3])
ppid = os.getppid()
def proc_text(name):
    try:
        return Path(f"/proc/{ppid}/{name}").read_bytes().decode("utf-8", "replace")
    except OSError:
        return ""
report = {
    "env_has_key_name": "CHANCELLOR_SUPERVISE_KEY" in os.environ,
    "env_has_dev_name": "CHANCELLOR_DEV_SIGNER_SECRET" in os.environ,
    "env_values_hold_key": any(key in v for v in os.environ.values()),
    "parent_environ_holds_key": key in proc_text("environ"),
    "parent_cmdline_holds_key": key in proc_text("cmdline"),
    "parent_cmdline_names_key_file": "--signing-key-file" in proc_text("cmdline"),
    "channel_named": receipts.SIGN_FD_ENV in os.environ,
}
log = AuditLog(log_path)
for i in range(3):
    request = EscalationRequest(
        action="segment", action_class=ActionClass.COMPUTE, detail=str(i)
    )
    log.record(Decision(request, True, "agent", "ok", time.time()))
log.checkpoint_v2()
try:
    log.signer.sign(b"not a checkpoint")
    report["junk_signed"] = True
except receipts.SigningRefused:
    report["junk_signed"] = False
report["signer"] = type(log.signer).__name__
report_path.write_text(json.dumps(report))
"""


def _run_supervise(tmp_path, *, key_mode):
    agent_py = tmp_path / "agent.py"
    agent_py.write_text(AGENT, encoding="utf-8")
    report = tmp_path / "report.json"
    state = tmp_path / "state"
    # The agent compares against the key it reads from here; the key is
    # not placed on the supervised command line.
    known = tmp_path / "known.txt"
    known.write_text(OPERATOR_SECRET, encoding="utf-8")
    log_path = state / "audit-log.jsonl"
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("CHANCELLOR_SUPERVISE_KEY", "CHANCELLOR_DEV_SIGNER_SECRET")
    }
    env["PYTHONPATH"] = SRC + os.pathsep + env.get("PYTHONPATH", "")
    args = [
        sys.executable,
        "-m",
        "chancellor.cli",
        "supervise",
        "--state-dir",
        str(state),
    ]
    if key_mode == "env":
        env["CHANCELLOR_SUPERVISE_KEY"] = OPERATOR_SECRET
    elif key_mode == "option":
        args += ["--signing-key", OPERATOR_SECRET]
    elif key_mode == "file":
        keyfile = tmp_path / "operator.key"
        keyfile.write_text(OPERATOR_SECRET, encoding="utf-8")
        keyfile.chmod(0o600)
        args += ["--signing-key-file", str(keyfile)]
    args += [
        "--cadence",
        "0.2",
        "--poll",
        "0.05",
        "--heartbeat",
        "2",
        "--",
        sys.executable,
        str(agent_py),
        str(known),
        str(report),
        str(log_path),
    ]
    proc = subprocess.run(args, env=env, capture_output=True, text=True, timeout=120)
    return proc, report, log_path, state


@pytest.mark.skipif(not Path("/proc/self/environ").exists(), reason="needs /proc")
@pytest.mark.parametrize("key_mode", ["env", "option", "file"])
def test_agent_never_holds_or_reads_the_operator_key(tmp_path, key_mode):
    proc, report_path, log_path, state = _run_supervise(tmp_path, key_mode=key_mode)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert OPERATOR_SECRET not in proc.stdout + proc.stderr
    report = json.loads(report_path.read_text())
    assert report["env_has_key_name"] is False
    assert report["env_has_dev_name"] is False
    assert report["env_values_hold_key"] is False
    assert report["parent_environ_holds_key"] is False
    assert report["parent_cmdline_holds_key"] is False
    assert report["parent_cmdline_names_key_file"] is False
    assert report["channel_named"] is True
    assert report["signer"] == "PipeSigner"
    assert report["junk_signed"] is False
    # The agent's log verifies under the operator's key, and under that
    # key's id only.
    result = verify_log(log_path, signer=operator_signer())
    assert result.ok and result.authentic, result.failures
    assert not verify_log(log_path, accept_dev_signer=True).consistent
    supervision = verify_log(state / "supervision-log.jsonl", signer=operator_signer())
    assert supervision.ok, supervision.failures


def test_signer_required_error_is_exported_from_package():
    import chancellor

    assert getattr(chancellor, "SignerRequiredError", None) is SignerRequiredError
