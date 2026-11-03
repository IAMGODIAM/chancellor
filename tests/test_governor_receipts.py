"""Governor decision receipts (SPEC §5): the §5.1 kinds ride the
shipped AuditLog spine — same chain, same fields, no new signing.
"""

import pytest

from chancellor.escalation import AuditLog
from chancellor.governor_receipts import RECEIPT_KINDS, GovernorReceipts


def test_mint_each_kind_and_query(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    for kind in RECEIPT_KINDS:
        receipts.mint(kind, {"rule": "X.Y", "artifact": "thing"})
    assert len(receipts.entries()) == len(RECEIPT_KINDS)
    for kind in RECEIPT_KINDS:
        assert len(receipts.entries(kind=kind)) == 1
    assert len(receipts.query(rule="X.Y")) == len(RECEIPT_KINDS)
    assert len(receipts.query(artifact="thing")) == len(RECEIPT_KINDS)
    assert receipts.query(rule="NOPE") == []


def test_unknown_kind_is_refused(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    with pytest.raises(ValueError, match="SPEC §5.1"):
        receipts.mint("telemetry", {})


def test_entries_ride_the_shipped_chain(tmp_path):
    path = tmp_path / "log.jsonl"
    receipts = GovernorReceipts(path)
    receipts.mint("policy-verdict", {"outcome": "verdict"})
    receipts.mint("routing", {"rule": "COMPUTE.GPU"})
    # Reopening through the shipped AuditLog re-verifies the chain.
    log = AuditLog(path)
    entries = log.read_all()
    assert len(entries) == 2
    assert entries[0]["entry_type"] == "governor_receipt"
    assert entries[1]["prev_hash"] == entries[0]["entry_hash"]
    assert all(e["frame_id"] for e in entries)


def test_checkpoint_v2_over_governor_entries(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    receipts.mint("drift", {"artifact": "canon-a"})
    checkpoint = receipts.checkpoint()
    assert checkpoint  # a signed v2 checkpoint dict came back
