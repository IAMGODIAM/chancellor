"""Build 3: freeze manifests + test runs as chained records, with a
fail-closed resolve verb (RepoZ pattern, delta REA §4.3).

Covers: manifest hashing/validation, entry builders, the generic
chained append, resolve happy path, and each named gap — manifest
without a test run, a test run bound to an unknown manifest, a
checkpoint that does not seal the entries, an absent manifest, and a
tampered chain.
"""

import json

import pytest

from chancellor import receipts
from chancellor.escalation import AuditLog
from chancellor.verify_log import main as verify_main
from chancellor.verify_log import resolve_manifest, verify_log

REPORT_SHA = "ab" * 32


def _files():
    return {
        "src/chancellor/receipts.py": receipts.sha256_hex(b"receipts"),
        "src/chancellor/verify_log.py": receipts.sha256_hex(b"verify"),
        "SPEC.md": receipts.sha256_hex(b"spec"),
    }


def _manifest_entry(log, files=None, suite_id="freeze-2026-11-04"):
    return log.record_entry(
        receipts.freeze_manifest_fields(
            files=_files() if files is None else files,
            suite_id=suite_id,
            head="deadbeef",
            recorded_by="freeze-seat",
            ts=1000.0,
        )
    )


def _test_run_entry(log, manifest_sha256, passed=155, failed=0):
    return log.record_entry(
        receipts.test_run_fields(
            suite="full-suite",
            command="python -m pytest -q",
            manifest_sha256=manifest_sha256,
            report_sha256=REPORT_SHA,
            report_path="war-room/freeze-report.md",
            passed=passed,
            failed=failed,
            seat="verifier-seat",
            ts=1001.0,
        )
    )


def test_manifest_hash_is_the_canonical_file_list():
    files = _files()
    digest = receipts.compute_manifest_sha256(files)
    # Order of the input mapping does not matter (canonical JSON).
    shuffled = dict(reversed(list(files.items())))
    assert receipts.compute_manifest_sha256(shuffled) == digest
    assert len(digest) == 64


def test_manifest_hash_validation():
    with pytest.raises(ValueError):
        receipts.compute_manifest_sha256({})
    with pytest.raises(ValueError):
        receipts.compute_manifest_sha256({"a.py": "not-a-hash"})
    with pytest.raises(ValueError):
        receipts.compute_manifest_sha256({"": "ab" * 32})


def test_entry_builders_validate():
    with pytest.raises(ValueError):
        receipts.test_run_fields(
            suite="s",
            command="c",
            manifest_sha256="zz" * 32,
            report_sha256=REPORT_SHA,
            passed=1,
            failed=0,
            seat="seat",
        )
    with pytest.raises(ValueError):
        receipts.test_run_fields(
            suite="s",
            command="c",
            manifest_sha256="ab" * 32,
            report_sha256=REPORT_SHA,
            passed=-1,
            failed=0,
            seat="seat",
        )
    with pytest.raises(ValueError):
        receipts.freeze_manifest_fields(
            files=_files(), suite_id="", head=None, recorded_by="seat"
        )


def test_record_entry_stamps_chain_and_refuses_reserved_fields(tmp_path):
    log = AuditLog(tmp_path / "audit.jsonl")
    entry = _manifest_entry(log)
    assert entry["seq"] == 0 and entry["prev_hash"] is None
    assert entry["schema"] == receipts.SCHEMA
    assert receipts.entry_hash(entry) == entry["entry_hash"]
    assert entry["entry_type"] == "freeze_manifest"
    assert entry["file_count"] == 3
    with pytest.raises(ValueError):
        log.record_entry({"seq": 99, "entry_type": "test_run"})


def test_freeze_entries_live_in_the_same_verified_chain(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, manifest["manifest_sha256"])
    log.checkpoint()
    result = verify_log(path)
    assert result.ok, result.failures
    assert result.chained_entries == 2


def test_resolve_happy_path(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, manifest["manifest_sha256"])
    log.checkpoint()
    result = resolve_manifest(path, manifest["manifest_sha256"])
    assert result.ok, result.failures
    assert result.manifest_entry["entry_hash"] == manifest["entry_hash"]
    assert len(result.test_runs) == 1
    assert result.test_runs[0]["passed"] == 155
    assert result.checkpoint["log_size"] == 2


def test_resolve_manifest_without_test_run_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    log.checkpoint()
    result = resolve_manifest(path, manifest["manifest_sha256"])
    assert not result.ok
    assert any(f.startswith("manifest_without_test_run") for f in result.failures)


def test_resolve_unknown_manifest_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, manifest["manifest_sha256"])
    log.checkpoint()
    result = resolve_manifest(path, "cd" * 32)
    assert not result.ok
    assert any(f.startswith("manifest_not_found") for f in result.failures)


def test_resolve_test_run_against_unknown_manifest_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, "ef" * 32)  # bound to a manifest never recorded
    log.checkpoint()
    result = resolve_manifest(path, manifest["manifest_sha256"])
    assert not result.ok
    assert any(f.startswith("test_run_unknown_manifest") for f in result.failures)


def test_resolve_checkpoint_not_covering_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    log.checkpoint()  # seals seq 0 only
    _test_run_entry(log, manifest["manifest_sha256"])  # lands after the seal
    result = resolve_manifest(path, manifest["manifest_sha256"])
    assert not result.ok
    assert any(f.startswith("checkpoint_not_covering") for f in result.failures)
    assert result.checkpoint is None


def test_resolve_no_checkpoint_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, manifest["manifest_sha256"])
    result = resolve_manifest(path, manifest["manifest_sha256"])
    assert not result.ok
    assert any(f.startswith("no_checkpoint") for f in result.failures)


def test_resolve_tampered_chain_fails_closed(tmp_path):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, manifest["manifest_sha256"])
    log.checkpoint()
    rows = log.read_all()
    rows[1]["passed"] = 999  # rewrite the recorded result after the fact
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    result = resolve_manifest(path, manifest["manifest_sha256"])
    assert not result.ok
    assert any(f.startswith("entry_hash_mismatch") for f in result.failures)


def test_resolve_cli_exit_codes(tmp_path, capsys):
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    manifest = _manifest_entry(log)
    _test_run_entry(log, manifest["manifest_sha256"])
    log.checkpoint()
    assert verify_main(["resolve", str(path), manifest["manifest_sha256"]]) == 0
    out = capsys.readouterr().out
    assert "RESOLVED" in out and "test_run:" in out and "sealed_by:" in out
    assert verify_main(["resolve", str(path), "cd" * 32]) == 1
    assert "NOT RESOLVED" in capsys.readouterr().out
    assert verify_main(["resolve", str(tmp_path / "missing.jsonl"), "ab" * 32]) == 2
