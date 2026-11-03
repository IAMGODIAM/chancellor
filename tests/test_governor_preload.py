"""Preload Service (SPEC §4): versioned, class-scoped, hard-budgeted
at issuance; canon changes invalidate the outstanding stamp.
"""

import pytest

from chancellor.governor_receipts import GovernorReceipts
from chancellor.manifest import Registry
from chancellor.preload import (
    CLASSES,
    SIZE_BUDGET_BYTES,
    PreloadBloatError,
    issue_preload,
)


def _registry(tmp_path, canon_text="Be excellent; measure first."):
    registry = Registry(tmp_path / "registry.json")
    canon = tmp_path / "canon.md"
    canon.write_text("canon body\n", encoding="utf-8")
    from chancellor.manifest import file_hash

    registry.add(
        {
            "name": "test-canon",
            "kind": "canon",
            "purpose": "test canon",
            "canonical_location": str(canon),
            "tier": "canonical",
            "state": "verified",
            "content_hash": file_hash(canon),
            "operative_text": canon_text,
        }
    )
    return registry


def test_every_class_issues_within_budget(tmp_path):
    registry = _registry(tmp_path)
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    for cls in CLASSES:
        issued = issue_preload(registry, receipts, cls, "a charge")
        assert issued["bytes"] <= SIZE_BUDGET_BYTES
        assert issued["stamp"].startswith(f"pl-{cls}-")
        assert "test-canon" in issued["text"]
    assert len(receipts.entries(kind="preload-issued")) == len(CLASSES)


def test_compute_preload_names_the_compute_rules(tmp_path):
    registry = _registry(tmp_path)
    issued = issue_preload(registry, None, "compute-heavy", "transcribe")
    for rule_id in ("COMPUTE.GPU", "COMPUTE.HEAVY", "COMPUTE.LIGHT"):
        assert rule_id in issued["text"]


def test_unknown_class_is_refused(tmp_path):
    registry = _registry(tmp_path)
    with pytest.raises(ValueError):
        issue_preload(registry, None, "nonsense-class", "a charge")


def test_canon_change_invalidates_the_outstanding_stamp(tmp_path):
    registry = _registry(tmp_path)
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    first = issue_preload(registry, receipts, "build", "first charge")
    versions = registry.meta["preload_versions"]["build"]
    assert versions["current"] == first["stamp"]

    # The canon entry is re-registered under a new hash.
    canon = tmp_path / "canon.md"
    canon.write_text("canon body, amended\n", encoding="utf-8")
    from chancellor.manifest import file_hash

    entry = dict(registry.get("test-canon"))
    entry["content_hash"] = file_hash(canon)
    registry.add(entry, receipts=receipts)

    versions = registry.meta["preload_versions"]["build"]
    assert versions["current"] is None
    assert first["stamp"] in versions["invalidated"]
    assert receipts.query(artifact="preload-class:build", kind="drift")

    second = issue_preload(registry, receipts, "build", "second charge")
    assert second["stamp"] != first["stamp"]


def test_over_budget_preload_never_issues(tmp_path):
    registry = _registry(tmp_path, canon_text="x" * (SIZE_BUDGET_BYTES + 1))
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    with pytest.raises(PreloadBloatError):
        issue_preload(registry, receipts, "build", "a charge")
    # The failure is receipted as a drift-kind finding; no issuance.
    assert receipts.entries(kind="drift")
    assert receipts.entries(kind="preload-issued") == []
    assert registry.meta["preload_versions"].get("build", {}).get("current") is None
