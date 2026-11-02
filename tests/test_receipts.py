"""Lane 2: hash-chained audit receipts + offline verifier.

Covers: chain round-trip, checkpoint consistency, and tamper detection
for a mid-log edit, tail truncation, reordering, a forged checkpoint
signature, and a doctored checkpoint root.
"""

import json

import pytest

from chancellor import receipts
from chancellor.escalation import ActionClass, AuditLog, EscalationRequest, Gatekeeper
from chancellor.verify_log import main as verify_main
from chancellor.verify_log import verify_log


def _spend(i=0):
    return EscalationRequest(
        action=f"spend #{i}",
        action_class=ActionClass.SPEND,
        cost_usd=1.0,
        node_id=f"n{i}",
    )


def _seed_log(path, n=5):
    log = AuditLog(path)
    gk = Gatekeeper(audit_log=log, approver=lambda req: (True, "ok"), human_id="tester")
    for i in range(n):
        gk.authorize(_spend(i))
    return log


def _rewrite(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_entries_are_chained_with_axes(tmp_path):
    log = _seed_log(tmp_path / "audit.jsonl", n=3)
    entries = log.read_all()
    assert [e["seq"] for e in entries] == [0, 1, 2]
    assert entries[0]["prev_hash"] is None
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]
    assert entries[2]["prev_hash"] == entries[1]["entry_hash"]
    for e in entries:
        assert receipts.entry_hash(e) == e["entry_hash"]
        assert e["schema"] == receipts.SCHEMA
        assert e["effect_axes"] == ["money_movement"]
        assert e["action_class"] == "spend"  # legacy class still recorded


def test_axes_for_each_class():
    assert receipts.effect_axes_for("publish") == [
        "external_visibility",
        "irreversibility",
    ]
    assert receipts.effect_axes_for("credential") == ["credential_exposure"]
    assert receipts.effect_axes_for("external_send") == ["external_visibility"]
    assert receipts.effect_axes_for("read") == []


def test_reopen_continues_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed_log(path, n=2)
    log2 = AuditLog(path)  # re-opens, re-verifies, continues
    Gatekeeper(audit_log=log2, approver=lambda req: (True, "ok")).authorize(_spend(2))
    entries = log2.read_all()
    assert len(entries) == 3
    assert entries[2]["seq"] == 2
    assert entries[2]["prev_hash"] == entries[1]["entry_hash"]


def test_checkpoint_roundtrip_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    envelope = log.checkpoint()
    payload = receipts.checkpoint_payload(envelope)
    assert payload["schema"] == receipts.CHECKPOINT_SCHEMA
    assert payload["log_size"] == 5
    assert payload["head_receipt_hash"] == log.read_all()[-1]["entry_hash"]
    assert receipts.checkpoint_signature_valid(envelope, log.signer)

    result = verify_log(path, accept_dev_signer=True)
    assert result.ok, result.failures
    assert result.chained_entries == 5 and result.checkpoints == 1


def test_verify_detects_mid_log_edit(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    log.checkpoint()
    rows = log.read_all()
    rows[2]["approved"] = False  # flip a decision after the fact
    _rewrite(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("entry_hash_mismatch") for f in result.failures)


def test_verify_detects_tail_truncation(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    log.checkpoint()
    _rewrite(path, log.read_all()[:3])  # drop the tail
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("tail_truncation") for f in result.failures)


def test_verify_detects_reordering(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    log.checkpoint()
    rows = log.read_all()
    rows[1], rows[2] = rows[2], rows[1]
    _rewrite(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(
        "seq_mismatch" in f or "prev_hash_link_broken" in f for f in result.failures
    )


def test_verify_detects_forged_checkpoint_signature(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    log.checkpoint()
    cp_path = receipts.default_checkpoint_path(path)
    env = json.loads(cp_path.read_text().splitlines()[0])
    env["signatures"][0]["sig"] = "AAAA" + env["signatures"][0]["sig"][4:]
    cp_path.write_text(json.dumps(env) + "\n")
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any("checkpoint_signature_invalid" in f for f in result.failures)


def test_verify_detects_doctored_checkpoint_root(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    log.checkpoint()
    cp_path = receipts.default_checkpoint_path(path)
    env = json.loads(cp_path.read_text().splitlines()[0])
    payload = receipts.checkpoint_payload(env)
    payload["merkle_root"] = "00" * 32
    # Rebuild the envelope unsigned-by-the-real-signer: both the root
    # check and the signature check must fire; at least root must name.
    env["payload"] = receipts._b64(receipts.canonical(payload))
    cp_path.write_text(json.dumps(env) + "\n")
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(
        "checkpoint_root_mismatch" in f or "checkpoint_signature_invalid" in f
        for f in result.failures
    )


def test_uncheckpointed_log_is_not_called_verified(tmp_path):
    path = tmp_path / "audit.jsonl"
    _seed_log(path, n=2)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("no_checkpoint") for f in result.failures)
    relaxed = verify_log(path, allow_uncheckpointed=True, accept_dev_signer=True)
    assert relaxed.ok and relaxed.warnings


def test_tampered_log_refuses_new_receipts(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    rows = log.read_all()
    rows[1]["rationale"] = "rewritten history"
    _rewrite(path, rows)
    with pytest.raises(receipts.ChainIntegrityError):
        AuditLog(path)


def test_legacy_prefix_anchors_and_is_reported(tmp_path):
    path = tmp_path / "audit.jsonl"
    legacy = {
        "ts": 1.0,
        "action": "old",
        "action_class": "spend",
        "detail": "",
        "cost_usd": None,
        "node_id": None,
        "approved": True,
        "decider": "policy",
        "rationale": "pre-chain",
    }
    path.write_text(json.dumps(legacy) + "\n")
    log = AuditLog(path)  # tolerated as a prefix
    Gatekeeper(audit_log=log, approver=lambda req: (True, "ok")).authorize(_spend(0))
    entries = log.read_all()
    assert entries[1]["seq"] == 1
    assert entries[1]["prev_hash"] == receipts.legacy_anchor(legacy)
    log.checkpoint()
    strict = verify_log(path, accept_dev_signer=True)
    assert not strict.ok
    assert any(f.startswith("unchained_legacy_entries") for f in strict.failures)
    assert verify_log(path, allow_legacy_prefix=True, accept_dev_signer=True).ok


def test_verifier_cli_exit_codes(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    log.checkpoint()
    assert verify_main([str(path), "--accept-dev-signer"]) == 0
    rows = log.read_all()
    rows[0]["approved"] = False
    _rewrite(path, rows)
    assert verify_main([str(path), "--accept-dev-signer"]) == 1
    assert "NOT VERIFIED" in capsys.readouterr().out
    assert verify_main([str(tmp_path / "missing.jsonl")]) == 2
