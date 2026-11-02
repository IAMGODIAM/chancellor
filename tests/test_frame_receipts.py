"""Button 3: frame-named receipts + receipts-on-refusal (Council M6/M10).

Covers: the governing frame cited inside the committed body of every
new receipt and gate verdict; tamper classes for the citation itself
(altered id, altered hash, stripped fields — each refused by name);
refusal receipts carrying their named state for every refusal path
the gate can reach; the frame document's hash recomputing to the
registry's; and pre-frame (v1) records verifying exactly as before.
"""

import hashlib
import json
from pathlib import Path

import pytest

from chancellor import receipts
from chancellor.escalation import (
    REFUSAL_APPROVER_DECLINED,
    REFUSAL_APPROVER_ERROR,
    REFUSAL_NO_APPROVER,
    ActionClass,
    AuditLog,
    EscalationRequest,
    Gatekeeper,
)
from chancellor.verify_log import verify_log

REPO_ROOT = Path(__file__).resolve().parent.parent


def _spend(i=0):
    return EscalationRequest(
        action=f"spend #{i}",
        action_class=ActionClass.SPEND,
        cost_usd=1.0,
        node_id=f"n{i}",
    )


def _seed_log(path, n=3):
    log = AuditLog(path)
    gk = Gatekeeper(audit_log=log, approver=lambda req: (True, "ok"), human_id="tester")
    for i in range(n):
        gk.authorize(_spend(i))
    return log


def _rewrite(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def test_new_gate_verdict_carries_frame_inside_committed_body(tmp_path):
    log = _seed_log(tmp_path / "audit.jsonl")
    for entry in log.read_all():
        assert entry["schema"] == receipts.SCHEMA
        assert entry["frame_id"] == receipts.FRAME_ID
        assert entry["frame_hash"] == receipts.FRAME_HASH
        # Inside the committed body: the entry hash recomputes over a
        # body that includes the frame fields, so the checkpoint-sealed
        # hash chain is what binds the citation.
        assert receipts.entry_hash(entry) == entry["entry_hash"]
        assert entry["refusal_state"] is None  # approvals: null, countable


def test_new_caller_shaped_receipt_carries_frame(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = log.record_entry(
        receipts.freeze_manifest_fields(
            files={"a.txt": "0" * 64}, suite_id="s", head=None, recorded_by="seat"
        )
    )
    assert entry["frame_id"] == receipts.FRAME_ID
    assert entry["frame_hash"] == receipts.FRAME_HASH
    assert receipts.entry_hash(entry) == entry["entry_hash"]


def test_caller_may_not_set_the_frame_citation(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    with pytest.raises(ValueError):
        log.record_entry({"entry_type": "test_run", "frame_id": "forged"})
    with pytest.raises(ValueError):
        log.record_entry({"entry_type": "test_run", "frame_hash": "0" * 64})


def test_frame_document_hash_recomputes_to_the_registry():
    doc = REPO_ROOT / receipts.FRAME_DOCUMENT
    digest = hashlib.sha256(doc.read_bytes()).hexdigest()
    assert digest == receipts.FRAME_HASH
    assert receipts.KNOWN_FRAMES[receipts.FRAME_ID] == receipts.FRAME_HASH
    # The document names the same identifier the code stamps.
    assert receipts.FRAME_ID in doc.read_text(encoding="utf-8")


def test_untampered_frame_era_log_verifies(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path)
    log.checkpoint()
    result = verify_log(path, accept_dev_signer=True)
    assert result.ok, result.failures


def test_frame_id_altered_fails_verification(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path)
    log.checkpoint()
    rows = log.read_all()
    rows[1]["frame_id"] = "e5.chancellor_frame.v99"
    _rewrite(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("frame_mismatch") for f in result.failures)
    assert any(f.startswith("entry_hash_mismatch") for f in result.failures)


def test_frame_hash_altered_fails_verification(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path)
    log.checkpoint()
    rows = log.read_all()
    rows[0]["frame_hash"] = "0" * 64
    _rewrite(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("frame_mismatch") for f in result.failures)


def test_frame_fields_stripped_refused_with_named_reason(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = _seed_log(path)
    log.checkpoint()
    rows = log.read_all()
    del rows[2]["frame_id"]
    del rows[2]["frame_hash"]
    _rewrite(path, rows)
    result = verify_log(path, accept_dev_signer=True)
    assert not result.ok
    assert any(f.startswith("frame_fields_missing") for f in result.failures)


def test_refusal_receipt_no_approver_attached(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    gk = Gatekeeper(audit_log=log)  # no approver: the gate does not open
    decision = gk.authorize(_spend())
    assert not decision.approved
    assert decision.refusal_state == REFUSAL_NO_APPROVER
    (entry,) = log.read_all()
    assert entry["approved"] is False
    assert entry["refusal_state"] == "no-approver-attached"
    assert entry["frame_id"] == receipts.FRAME_ID
    assert entry["frame_hash"] == receipts.FRAME_HASH
    log.checkpoint()
    result = verify_log(path, accept_dev_signer=True)
    assert result.ok, result.failures  # a refusal verifies like any record


def test_refusal_receipt_approver_declined(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    gk = Gatekeeper(
        audit_log=log,
        approver=lambda req: (False, "not this quarter"),
        human_id="tester",
    )
    decision = gk.authorize(_spend())
    assert not decision.approved
    assert decision.refusal_state == REFUSAL_APPROVER_DECLINED
    (entry,) = log.read_all()
    assert entry["refusal_state"] == "approver-declined"
    assert entry["frame_id"] == receipts.FRAME_ID


def test_refusal_receipt_approver_error_fail_closed(tmp_path):
    def broken(_req):
        raise RuntimeError("approver unreachable")

    log = AuditLog(tmp_path / "audit.jsonl")
    gk = Gatekeeper(audit_log=log, approver=broken, human_id="tester")
    decision = gk.authorize(_spend())
    assert not decision.approved
    assert decision.refusal_state == REFUSAL_APPROVER_ERROR
    (entry,) = log.read_all()
    assert entry["refusal_state"] == "approver-error"
    assert entry["frame_hash"] == receipts.FRAME_HASH


def test_pre_frame_sample_evidence_verifies_unchanged():
    sample = REPO_ROOT / "docs" / "evidence" / "sample" / "audit-log.jsonl"
    result = verify_log(sample, accept_dev_signer=True)
    assert result.ok, result.failures
    rows = [
        json.loads(line) for line in sample.read_text().splitlines() if line.strip()
    ]
    assert rows and all("frame_id" not in r for r in rows)  # truly pre-frame
