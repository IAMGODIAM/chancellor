"""Checkpoint v2 for the Chancellor mirror: RFC 9162 tree,
count-in-anchor, standalone holder proofs.

The v1 defect pinned here: the v1 Merkle construction promotes an odd
leaf by duplication, so root([a,b,c]) == root([a,b,c,c]) — a bare root
never commits to the count. v2 must make that collision impossible,
refuse proofs whose count disagrees with the checkpoint, verify a
holder-presented proof without the log — and v1 checkpoints must keep
verifying under v1 rules (dual-verify; test_receipts.py covers v1).
"""

import hashlib
import json

from chancellor import receipts
from chancellor.escalation import ActionClass, AuditLog, EscalationRequest, Gatekeeper
from chancellor.verify_log import main as verify_main
from chancellor.verify_log import verify_holder_proof, verify_log


def _leaf(i: int) -> str:
    return hashlib.sha256(f"leaf-{i}".encode()).hexdigest()


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


# ---------------------------------------------------------- tree shape
def test_v1_collision_documented_v2_repaired():
    a, b, c = _leaf(0), _leaf(1), _leaf(2)
    # the v1 defect, pinned as a fact about v1:
    assert receipts.merkle_root([a, b, c]) == receipts.merkle_root([a, b, c, c])
    # v2: duplication never enters the construction
    assert receipts.rfc9162_root([a, b, c]) != receipts.rfc9162_root([a, b, c, c])
    assert receipts.rfc9162_root([a, b, c]) != receipts.rfc9162_root([a, b])


def test_anchor_digest_binds_count():
    """[a,b,c] vs [a,b,c,c]: payloads differing only in the tree (and
    size) must yield different anchor digests — under v1's bare-root
    anchoring the external commitment was the same 32 bytes."""
    signer = receipts.default_signer()
    leaves3 = [_leaf(i) for i in range(3)]
    leaves4 = leaves3 + [leaves3[-1]]
    env3 = receipts.build_checkpoint_v2(
        signer=signer, log_size=3, leaves=leaves3, head_hash=leaves3[-1]
    )
    env4 = receipts.build_checkpoint_v2(
        signer=signer, log_size=4, leaves=leaves4, head_hash=leaves4[-1]
    )
    p3, p4 = receipts.checkpoint_payload(env3), receipts.checkpoint_payload(env4)
    assert p3["merkle_root"] != p4["merkle_root"]
    assert receipts.checkpoint_anchor_digest(p3) != receipts.checkpoint_anchor_digest(
        p4
    )
    # v1's anchored quantity (the bare root) for the same pair collides:
    assert receipts.merkle_root(leaves3) == receipts.merkle_root(leaves4)


def test_rfc9162_proofs_round_trip():
    for n in range(1, 13):
        leaves = [_leaf(i) for i in range(n)]
        root = receipts.rfc9162_root(leaves)
        for idx in range(n):
            proof = receipts.rfc9162_proof(leaves, idx)
            assert receipts.rfc9162_verify(
                proof["leaf_hash"], idx, n, proof["path"], root
            )


# ------------------------------------------------------ log + verify
def test_v2_checkpoint_roundtrip_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    envelope = log.checkpoint_v2()
    payload = receipts.checkpoint_payload(envelope)
    assert payload["schema"] == receipts.CHECKPOINT_SCHEMA_V2
    assert payload["tree"] == "rfc9162"
    assert payload["log_size"] == 5
    assert payload["head_receipt_hash"] == log.read_all()[-1]["entry_hash"]
    assert receipts.checkpoint_signature_valid(envelope, log.signer)

    result = verify_log(path, accept_dev_signer=True)
    assert result.ok, result.failures
    assert result.chained_entries == 5 and result.checkpoints == 1


def test_v2_checkpoint_detects_tail_truncation(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    log.checkpoint_v2()
    rows = log.read_all()[:3]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("tail_truncation") for f in result.failures)


def test_mixed_sidecar_newest_checkpoint_rules(tmp_path):
    """Dual-verify in one sidecar: a v1 checkpoint followed by a v2 —
    the newest (v2) is the one checked, under v2 rules."""
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    log.checkpoint()  # v1
    log.checkpoint_v2()  # v2, newest
    result = verify_log(path, accept_dev_signer=True)
    assert result.ok, result.failures
    assert result.checkpoints == 2


# ------------------------------------------------- standalone proofs
def test_holder_proof_round_trip_without_log(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=5)
    log.checkpoint_v2()
    leaves = [e["entry_hash"] for e in log.read_all()]
    cp_path = receipts.default_checkpoint_path(path)
    for idx in range(5):
        proof = receipts.rfc9162_proof(leaves, idx)
        result = verify_holder_proof(cp_path, proof, accept_dev_signer=True)
        assert result.ok, (idx, result.failures)
    # the log file itself is never consulted: delete it and re-verify
    path.unlink()
    proof = receipts.rfc9162_proof(leaves, 2)
    assert verify_holder_proof(cp_path, proof, accept_dev_signer=True).ok


def test_holder_proof_count_mismatch_is_refused(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    log.checkpoint_v2()
    leaves = [e["entry_hash"] for e in log.read_all()]
    proof = receipts.rfc9162_proof(leaves, 1)
    proof["tree_size"] = 4  # claim a larger tree than the checkpoint's
    result = verify_holder_proof(
        receipts.default_checkpoint_path(path), proof, accept_dev_signer=True
    )
    assert not result.ok
    assert any(f.startswith("proof_count_mismatch") for f in result.failures)


def test_holder_proof_tampering_fails(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=4)
    log.checkpoint_v2()
    leaves = [e["entry_hash"] for e in log.read_all()]
    cp_path = receipts.default_checkpoint_path(path)
    proof = receipts.rfc9162_proof(leaves, 2)
    forged_leaf = dict(proof, leaf_hash=_leaf(777))
    assert not verify_holder_proof(cp_path, forged_leaf, accept_dev_signer=True).ok
    swapped = dict(proof, index=3)
    assert not verify_holder_proof(cp_path, swapped, accept_dev_signer=True).ok
    bad_path = dict(proof, path=[_leaf(888)] + proof["path"][1:])
    result = verify_holder_proof(cp_path, bad_path, accept_dev_signer=True)
    assert not result.ok
    assert any("inclusion_proof_invalid" in f for f in result.failures)


def test_holder_proof_rejects_v1_checkpoint(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=2)
    log.checkpoint()  # v1 only
    leaves = [e["entry_hash"] for e in log.read_all()]
    proof = receipts.rfc9162_proof(leaves, 0)
    result = verify_holder_proof(
        receipts.default_checkpoint_path(path), proof, accept_dev_signer=True
    )
    assert not result.ok
    assert any(f.startswith("checkpoint_schema") for f in result.failures)


def test_holder_proof_cli(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path, n=3)
    log.checkpoint_v2()
    leaves = [e["entry_hash"] for e in log.read_all()]
    proof_path = tmp_path / "proof.json"
    proof_path.write_text(json.dumps(receipts.rfc9162_proof(leaves, 1)))
    assert (
        verify_main([str(path), "--proof", str(proof_path), "--accept-dev-signer"]) == 0
    )
    assert "VERIFIED" in capsys.readouterr().out
    bad = receipts.rfc9162_proof(leaves, 1)
    bad["tree_size"] = 9
    proof_path.write_text(json.dumps(bad))
    assert (
        verify_main([str(path), "--proof", str(proof_path), "--accept-dev-signer"]) == 1
    )
    assert "proof_count_mismatch" in capsys.readouterr().out
