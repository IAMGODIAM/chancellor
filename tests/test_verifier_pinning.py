"""Verifier strictness: a log is authentic only under a pinned, non-dev
signer; dev-signed logs are labelled and never verified; checkpoint
history, key ids and outcome records are checked."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pinning import (
    OPERATOR_SECRET,
    Ed25519TestSigner,
    operator_signer,
    pin_args,
)

from chancellor import receipts
from chancellor.escalation import (
    ActionClass,
    AuditLog,
    EscalationRequest,
    Gatekeeper,
)
from chancellor.verify_log import (
    DEV_SIGNER_LABEL,
    load_pinned_signer,
    resolve_manifest,
    verify_log,
)
from chancellor.verify_log import main as verify_main

REPO = Path(__file__).resolve().parent.parent


def _spend(i: int) -> EscalationRequest:
    return EscalationRequest(
        action=f"pay vendor {i}", action_class=ActionClass.SPEND, node_id=f"n{i}"
    )


def _log(path: Path, signer=None, *, approve=True, n=4, **kwargs) -> AuditLog:
    log = AuditLog(path, signer=signer, **kwargs)
    approver = (lambda _r: (True, "ok")) if approve else None
    gk = Gatekeeper(audit_log=log, approver=approver, human_id="tester")
    for i in range(n):
        gk.authorize(_spend(i))
    return log


def _rewrite(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _forge_and_reseal_with_dev_key(path: Path) -> None:
    """Flip the first denial to an approval, re-chain, and seal the
    result under the public dev key."""
    rows = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    prev = None
    flipped = False
    for row in rows:
        if not flipped and row.get("approved") is False:
            row.update(approved=True, refusal_state=None, decider="alice")
            flipped = True
        row["prev_hash"] = prev
        row.pop("entry_hash", None)
        row["entry_hash"] = receipts.entry_hash(row)
        prev = row["entry_hash"]
    assert flipped
    _rewrite(path, rows)
    leaves = [r["entry_hash"] for r in rows]
    envelope = receipts.build_checkpoint_v2(
        signer=receipts.public_dev_signer(),
        log_size=len(rows),
        leaves=leaves,
        head_hash=prev,
    )
    receipts.default_checkpoint_path(path).write_text(
        json.dumps(envelope) + "\n", encoding="utf-8"
    )


# --------------------------------------------------- the pinned-key path
def test_ed25519_verifier_matches_rfc8032_vectors():
    pk = bytes.fromhex(
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    )
    sig = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555f"
        "b8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    assert receipts.ed25519_verify(pk, b"", sig)
    assert not receipts.ed25519_verify(pk, b"x", sig)
    assert not receipts.ed25519_verify(pk, b"", sig[:-1] + b"\x00")
    assert not receipts.ed25519_verify(pk[:-1], b"", sig)


def test_pinned_ed25519_log_is_authentic_and_cli_exits_zero(tmp_path, capsys):
    key = Ed25519TestSigner()
    path = tmp_path / "audit.jsonl"
    _log(path, key).checkpoint_v2()
    assert verify_main([str(path), "--pubkey", key.public_text]) == 0
    out = capsys.readouterr().out
    assert "VERIFIED" in out and key.key_id in out
    result = verify_log(path, signer=load_pinned_signer(key.public_text))
    assert result.ok and result.authentic and not result.dev_signer


def test_pubkey_may_be_a_file(tmp_path):
    key = Ed25519TestSigner()
    path = tmp_path / "audit.jsonl"
    _log(path, key).checkpoint_v2()
    keyfile = tmp_path / "signer.pub"
    keyfile.write_text(key.public_text + "\n", encoding="utf-8")
    assert verify_main([str(path), "--pubkey", str(keyfile)]) == 0


def test_wrong_pinned_key_is_not_authentic(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    _log(path, Ed25519TestSigner()).checkpoint_v2()
    other = Ed25519TestSigner()
    assert verify_main([str(path), "--pubkey", other.public_text]) == 1
    out = capsys.readouterr().out
    assert "signer_not_pinned" in out and "NOT VERIFIED" in out


def test_resealed_forgery_is_rejected_under_a_pinned_key(tmp_path, capsys):
    """A log rewritten and re-sealed with the public dev key does not
    verify against the key the user pinned, and is labelled without one."""
    key = Ed25519TestSigner()
    path = tmp_path / "audit.jsonl"
    log = _log(path, key, approve=False)
    log.checkpoint_v2()
    assert verify_main([str(path), "--pubkey", key.public_text]) == 0
    capsys.readouterr()

    _forge_and_reseal_with_dev_key(path)
    assert verify_main([str(path), "--pubkey", key.public_text]) == 1
    pinned_out = capsys.readouterr().out
    assert "signer_not_pinned" in pinned_out
    assert "VERIFIED" not in pinned_out.replace("NOT VERIFIED", "")

    assert verify_main([str(path)]) == 1
    unpinned_out = capsys.readouterr().out
    assert DEV_SIGNER_LABEL in unpinned_out
    assert "VERIFIED" not in unpinned_out.replace("NOT VERIFIED", "")


def test_dev_signed_never_exits_zero_even_when_acknowledged(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    _log(path).checkpoint_v2()
    for argv in ([str(path)], [str(path), "--accept-dev-signer"]):
        assert verify_main(argv) == 1
        out = capsys.readouterr().out
        assert DEV_SIGNER_LABEL in out
        assert "VERIFIED" not in out.replace("NOT VERIFIED", "")
    result = verify_log(path, accept_dev_signer=True)
    assert result.consistent and result.dev_signer and not result.authentic


def test_pinning_the_dev_key_is_still_not_authentic(tmp_path):
    path = tmp_path / "audit.jsonl"
    _log(path).checkpoint_v2()
    assert verify_main([str(path), "--pubkey", receipts.DEV_SIGNER_KEY_ID]) == 1


def test_unsealed_log_is_never_authentic(tmp_path):
    path = tmp_path / "audit.jsonl"
    _log(path, operator_signer(), checkpoint_every=None)
    result = verify_log(path, allow_uncheckpointed=True, signer=operator_signer())
    assert not result.authentic
    assert verify_main([str(path), "--allow-uncheckpointed"]) == 1


def test_operator_key_id_pin_needs_the_matching_secret(tmp_path, monkeypatch, capsys):
    path = tmp_path / "audit.jsonl"
    _log(path, operator_signer()).checkpoint_v2()
    pin = pin_args(monkeypatch)
    assert verify_main([str(path), *pin]) == 0
    monkeypatch.setenv(receipts.VERIFY_KEY_ENV, OPERATOR_SECRET + "-other")
    assert verify_main([str(path), *pin]) == 2
    assert "does not match" in capsys.readouterr().err
    monkeypatch.delenv(receipts.VERIFY_KEY_ENV)
    assert verify_main([str(path), *pin]) == 2


@pytest.mark.parametrize("bad", ["not-a-key", "ed25519:" + "ab" * 8, "zz" * 32, ""])
def test_unusable_pin_is_a_usage_error(tmp_path, bad, capsys):
    path = tmp_path / "audit.jsonl"
    _log(path, operator_signer()).checkpoint_v2()
    assert verify_main([str(path), "--pubkey", bad]) == 2
    capsys.readouterr()


def test_operator_secret_has_its_own_key_id():
    assert operator_signer().key_id.startswith(receipts.HMAC_KEY_ID_PREFIX)
    assert operator_signer().key_id != receipts.DEV_SIGNER_KEY_ID
    assert receipts.HmacSigner(secret=receipts.DEV_SIGNER_SECRET).is_dev
    assert OPERATOR_SECRET not in operator_signer().key_id


# ------------------------------------- the flag lives only in --help
def test_accept_dev_signer_is_absent_from_user_facing_copy():
    for rel in (
        "README.md",
        "docs/evidence/sample/README.md",
        "docs/supervision-cadence.md",
    ):
        assert "accept-dev-signer" not in (REPO / rel).read_text(encoding="utf-8"), rel


def test_accept_dev_signer_appears_only_in_help(capsys):
    with pytest.raises(SystemExit):
        verify_main(["--help"])
    help_text = capsys.readouterr().out
    assert "--accept-dev-signer" in help_text
    assert "non-production signer" in help_text
    assert "--pubkey" in help_text


def _src_env() -> dict[str, str]:
    """Child env that imports chancellor from this checkout (CI does not install it)."""
    import chancellor

    src = str(Path(chancellor.__file__).resolve().parent.parent)
    env = dict(os.environ)
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    return env


def test_demo_prints_no_flag_guidance(tmp_path):
    proc = subprocess.run(
        [sys.executable, "-m", "chancellor.cli", "demo", "--fast", "--auto"],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env=_src_env(),
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "accept-dev-signer" not in proc.stdout
    assert DEV_SIGNER_LABEL in proc.stdout


# ------------------------------------------ checkpoint history checks
def test_v1_checkpoint_after_v2_is_rejected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _log(path, operator_signer(), n=3, checkpoint_every=None)
    log.checkpoint_v2()
    log.checkpoint_path.write_text(
        log.checkpoint_path.read_text()
        + json.dumps(
            receipts.build_checkpoint(
                signer=operator_signer(),
                log_size=3,
                leaves=[e["entry_hash"] for e in log.read_all()],
                head_hash=log.read_all()[-1]["entry_hash"],
            )
        )
        + "\n"
    )
    result = verify_log(path, signer=operator_signer())
    assert not result.ok
    assert any("checkpoint_schema_downgrade" in f for f in result.failures)


def test_checkpoint_method_never_writes_v1_after_v2(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _log(path, operator_signer(), n=3, checkpoint_every=None)
    log.checkpoint_v2()
    envelope = log.checkpoint()
    assert (
        receipts.checkpoint_payload(envelope)["schema"] == receipts.CHECKPOINT_SCHEMA_V2
    )
    assert verify_log(path, signer=operator_signer()).ok


def test_auto_seal_writes_v2(tmp_path):
    log = _log(tmp_path / "a.jsonl", operator_signer(), n=4, checkpoint_every=2)
    schemas = [
        receipts.checkpoint_payload(json.loads(line))["schema"]
        for line in log.checkpoint_path.read_text().splitlines()
    ]
    assert schemas == [receipts.CHECKPOINT_SCHEMA_V2] * 2


def test_older_checkpoint_that_disagrees_with_the_log_is_rejected(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _log(path, operator_signer(), n=4, checkpoint_every=2)
    assert verify_log(path, signer=operator_signer()).ok
    # Rewrite entry 0 and re-chain: the later seal no longer matches, and
    # neither does the earlier one.
    rows = log.read_all()
    rows[0]["rationale"] = "changed"
    prev = None
    for row in rows:
        row["prev_hash"] = prev
        row["entry_hash"] = receipts.entry_hash(row)
        prev = row["entry_hash"]
    _rewrite(path, rows)
    result = verify_log(path, signer=operator_signer())
    assert not result.ok
    assert any("checkpoint_history_inconsistent" in f for f in result.failures)


def test_checkpoint_size_may_not_regress(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _log(path, operator_signer(), n=4, checkpoint_every=2)
    lines = log.checkpoint_path.read_text().splitlines()
    log.checkpoint_path.write_text("\n".join(reversed(lines)) + "\n")
    result = verify_log(path, signer=operator_signer())
    assert any("checkpoint_size_regressed" in f for f in result.failures)


def test_resolve_reads_v2_checkpoints(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path, signer=operator_signer(), checkpoint_every=None)
    manifest = log.record_entry(
        receipts.freeze_manifest_fields(
            files={"a.py": "ab" * 32},
            suite_id="s",
            head=None,
            recorded_by="tester",
        )
    )
    log.record_entry(
        receipts.test_run_fields(
            suite="s",
            command="pytest",
            manifest_sha256=manifest["manifest_sha256"],
            report_sha256="cd" * 32,
            passed=1,
            failed=0,
            seat="tester",
        )
    )
    log.checkpoint_v2()
    result = resolve_manifest(
        path, manifest["manifest_sha256"], signer=operator_signer()
    )
    assert result.ok and result.authentic
    pin = pin_args(monkeypatch)
    assert verify_main(["resolve", str(path), manifest["manifest_sha256"], *pin]) == 0


# ---------------------------------------------------- outcome records
def _brokered_log(tmp_path: Path):
    from chancellor.interception import ToolBroker

    log = AuditLog(tmp_path / "audit.jsonl", signer=operator_signer())
    gk = Gatekeeper(audit_log=log, approver=lambda _r: (True, "ok"))
    broker = ToolBroker(gatekeeper=gk)
    broker.register("wire_transfer", lambda **_kw: "sent")
    broker.call("n1", "wire_transfer", {"amount": 5})
    return log, broker


def test_brokered_call_leaves_decision_and_outcome_on_the_chain(tmp_path):
    log, broker = _brokered_log(tmp_path)
    log.checkpoint_v2()
    decision, outcome = log.read_all()
    assert decision["call_id"] == outcome["call_id"]
    assert outcome["entry_type"] == receipts.ENTRY_TYPE_TOOL_OUTCOME
    assert outcome["tool"] == "wire_transfer"
    assert outcome["result_status"] == "ok"
    assert outcome["approved_args_sha256"] == decision["args_sha256"]
    assert outcome["executed_args_sha256"] == decision["args_sha256"]
    assert outcome["result_sha256"]
    assert verify_log(log.path, signer=operator_signer()).authentic


def test_approval_without_outcome_fails_verification(tmp_path):
    log, _ = _brokered_log(tmp_path)
    rows = log.read_all()[:1]  # drop the outcome and re-seal
    path = log.path
    _rewrite(path, rows)
    log.checkpoint_path.unlink(missing_ok=True)
    AuditLog(path, signer=operator_signer()).checkpoint_v2()
    result = verify_log(path, signer=operator_signer())
    assert not result.ok
    assert any("approval_without_outcome" in f for f in result.failures)


def test_outcome_that_ran_other_arguments_fails_verification(tmp_path):
    log, _ = _brokered_log(tmp_path)
    rows = log.read_all()
    rows[1]["executed_args_sha256"] = "00" * 32
    prev = rows[0]["entry_hash"]
    rows[1]["prev_hash"] = prev
    rows[1]["entry_hash"] = receipts.entry_hash(rows[1])
    _rewrite(log.path, rows)
    log.checkpoint_path.unlink(missing_ok=True)
    AuditLog(log.path, signer=operator_signer()).checkpoint_v2()
    result = verify_log(log.path, signer=operator_signer())
    assert any("outcome_args_mismatch" in f for f in result.failures)


def test_outcome_with_no_approved_decision_fails_verification(tmp_path):
    log, _ = _brokered_log(tmp_path)
    rows = log.read_all()[1:]
    rows[0]["seq"] = 0
    rows[0]["prev_hash"] = None
    rows[0]["entry_hash"] = receipts.entry_hash(rows[0])
    _rewrite(log.path, rows)
    log.checkpoint_path.unlink(missing_ok=True)
    AuditLog(log.path, signer=operator_signer()).checkpoint_v2()
    result = verify_log(log.path, signer=operator_signer())
    assert any("outcome_without_approval" in f for f in result.failures)


def test_dev_id_pin_uses_public_key_independent_of_environment(monkeypatch):
    from chancellor.verify_log import load_pinned_signer

    monkeypatch.setenv("CHANCELLOR_DEV_SIGNER_SECRET", "throwaway-override-" * 3)
    signer = load_pinned_signer(receipts.DEV_SIGNER_KEY_ID)
    assert signer.key_id == receipts.DEV_SIGNER_KEY_ID
    assert signer.sign(b"test") == receipts.public_dev_signer().sign(b"test")


def test_resolved_key_id_must_match_literal_id_pin(monkeypatch):
    from chancellor.verify_log import load_pinned_signer

    monkeypatch.setattr(receipts, "public_dev_signer", operator_signer)
    with pytest.raises(ValueError, match="pinned key id"):
        load_pinned_signer(receipts.DEV_SIGNER_KEY_ID)
