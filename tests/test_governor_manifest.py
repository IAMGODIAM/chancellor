"""Manifest Registry (SPEC §3): schema, the self-entry, and drift
verification — expected vs found, with the fix the entry's shape
affords (mirror push, registry correction, or a staged finding).
"""

import pytest

from chancellor.governor_receipts import GovernorReceipts
from chancellor.manifest import Registry, file_hash


def _registry(tmp_path):
    return Registry(tmp_path / "registry.json")


def _entry(name, location, **kw):
    base = {
        "name": name,
        "kind": "canon",
        "purpose": "test entry",
        "canonical_location": str(location),
        "tier": "canonical",
        "state": "unverified",
    }
    base.update(kw)
    return base


def test_add_get_and_schema_guards(tmp_path):
    registry = _registry(tmp_path)
    registry.add(_entry("canon-a", tmp_path / "a.md"))
    assert registry.get("canon-a")["name"] == "canon-a"
    assert registry.get("missing") is None
    with pytest.raises(ValueError):
        registry.add(_entry("bad", tmp_path / "b.md", kind="nonsense"))
    with pytest.raises(ValueError):
        registry.add(_entry("bad", tmp_path / "b.md", tier="cloud"))
    with pytest.raises(ValueError):
        registry.add({"name": "bad", "kind": "canon"})


def test_registry_registers_itself(tmp_path):
    registry = _registry(tmp_path)
    registry.save()
    entry = registry.ensure_self_entry()
    assert entry["name"] == "manifest-registry"
    assert entry["content_hash"] == file_hash(tmp_path / "registry.json")


def test_verify_clean_file_marks_verified(tmp_path):
    target = tmp_path / "canon.md"
    target.write_text("the canon\n", encoding="utf-8")
    registry = _registry(tmp_path)
    registry.add(_entry("canon-a", target, content_hash=file_hash(target)))
    report = registry.verify()
    assert report["findings"] == []
    assert report["checked"] == 1
    assert registry.get("canon-a")["state"] == "verified"
    assert registry.get("canon-a")["verified_by"]


def test_verify_canonical_drift_corrects_registry_with_receipt(tmp_path):
    target = tmp_path / "canon.md"
    target.write_text("version two\n", encoding="utf-8")
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    registry = _registry(tmp_path)
    registry.add(_entry("canon-a", target, content_hash="0" * 64))
    report = registry.verify(receipts=receipts)
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["expected"] == "0" * 64
    assert finding["found"] == file_hash(target)
    assert registry.get("canon-a")["content_hash"] == file_hash(target)
    assert registry.get("canon-a")["state"] == "corrected"
    drift = receipts.entries(kind="drift")
    assert len(drift) == 1
    assert drift[0]["artifact"] == "canon-a"


def test_verify_mirror_drift_pushes_the_canonical_copy(tmp_path):
    canonical = tmp_path / "canon.md"
    canonical.write_text("the truth\n", encoding="utf-8")
    mirror = tmp_path / "archive" / "canon.md"
    mirror.parent.mkdir()
    mirror.write_text("a regressed copy\n", encoding="utf-8")
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    registry = _registry(tmp_path)
    registry.add(
        _entry("canon-archive-copy", mirror, tier="mirror", mirror_of=str(canonical))
    )
    report = registry.verify(receipts=receipts)
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["expected"] == file_hash(canonical)
    assert finding["found"] != finding["expected"]
    # The corrected copy is pushed: the mirror now holds the canon.
    assert mirror.read_text(encoding="utf-8") == "the truth\n"
    assert registry.get("canon-archive-copy")["state"] == "corrected"
    assert receipts.entries(kind="drift")


def test_verify_missing_canonical_stages_the_decision(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    registry = _registry(tmp_path)
    registry.add(_entry("canon-gone", tmp_path / "gone.md", content_hash="a" * 64))
    report = registry.verify(receipts=receipts)
    assert len(report["findings"]) == 1
    assert report["findings"][0]["found"] == "missing"
    assert "staged" in report["findings"][0]["fix"]
    assert registry.get("canon-gone")["state"] == "staged"


def test_verify_skips_remotes_directories_and_globs(tmp_path):
    registry = _registry(tmp_path)
    registry.add(_entry("remote", "E5EnclaveInc/agent-skills:skills/x"))
    registry.add(_entry("dir", tmp_path))
    registry.add(_entry("glob", "~/workspace/goals/*/crons/", kind="schedule"))
    report = registry.verify()
    assert report["checked"] == 0
    assert report["skipped"] == 3
    assert report["findings"] == []


def test_verify_slice_filters_by_kind(tmp_path):
    target = tmp_path / "canon.md"
    target.write_text("x\n", encoding="utf-8")
    registry = _registry(tmp_path)
    registry.add(_entry("canon-a", target, content_hash=file_hash(target)))
    registry.add(
        _entry(
            "sched-a", tmp_path / "missing.md", kind="schedule", content_hash="b" * 64
        )
    )
    report = registry.verify(slice_kind="canon")
    assert report["checked"] == 1
    assert report["findings"] == []
