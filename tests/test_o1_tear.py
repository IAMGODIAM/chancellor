"""O1 regression family — the torn log/sidecar pair read.

The defect (shipped supervisor, R7 path): verify_at_checkpoint_boundary
reads the agent log first and the checkpoint sidecar second. A writer
that appends + checkpoints between the two reads leaves the sidecar's
log_size one entry ahead of the counted entries, and the tear was
returned as tail_truncation — the supervisor halted a healthy live
agent on a false drift verdict (filed sightings: "checkpoint covers
27 chained entries, log holds 26"; the same state re-verified clean
cold, 27/27).

The cure (recount-on-tear): on the tail_truncation signature alone,
the verifier re-reads the pair fresh and judges on the consistent
second read alone. A truncation that persists across the recount is
real and still fails; one that vanishes was the tear.

The tear is reproduced deterministically at the verifier's own seam:
_parse_jsonl_lenient is wrapped so the writer moves (append +
checkpoint) between the log read and the sidecar read, exactly as
the live race did — no threads, no timing.
"""

import time
from pathlib import Path

import chancellor.supervise as supervise
from chancellor.escalation import (
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
)
from chancellor.supervise import verify_at_checkpoint_boundary


def _record_segment(log: AuditLog, i: int) -> None:
    request = EscalationRequest(
        action="segment",
        action_class=ActionClass.COMPUTE,
        detail=f"segment {i}",
    )
    log.record(Decision(request, True, "agent", "committed", time.time()))
    log.checkpoint()


def _agent_log(path: Path, segments: int) -> AuditLog:
    """An agent's governed record: `segments` receipts, each sealed
    with a signed checkpoint as it lands."""
    log = AuditLog(path)
    for i in range(segments):
        _record_segment(log, i)
    return log


def _wrap_parse(monkeypatch, log_path: Path, on_log_read) -> dict:
    """Wrap supervise._parse_jsonl_lenient: after each real read of
    the LOG (never the sidecar), invoke on_log_read(read_number) —
    the writer's move, landing between the verifier's two reads."""
    real_parse = supervise._parse_jsonl_lenient
    state = {"log_reads": 0}

    def wrapped(path):
        rows, torn = real_parse(path)
        if Path(path) == log_path:
            state["log_reads"] += 1
            on_log_read(state["log_reads"])
        return rows, torn

    monkeypatch.setattr(supervise, "_parse_jsonl_lenient", wrapped)
    return state


# ------------------------------------------------------- the tear
def test_o1_torn_pair_verifies_clean_on_recount(tmp_path, monkeypatch):
    log_path = tmp_path / "audit-log.jsonl"
    log = _agent_log(log_path, 3)

    def writer_moves_once(read_number: int) -> None:
        if read_number == 1:
            _record_segment(log, 3)  # append + checkpoint mid-verify

    state = _wrap_parse(monkeypatch, log_path, writer_moves_once)
    result = verify_at_checkpoint_boundary(log_path)
    assert result.ok, result.failures
    # Judged on the fresh pair: the checkpoint sealing segment 3.
    assert result.log_size == 4
    assert result.entries_present == 4
    # The recount actually happened: the log was read a second time.
    assert state["log_reads"] == 2
    assert any("tail_truncation_recounted" in w for w in result.warnings)


def test_o1_consistent_pair_is_read_once_no_recount(tmp_path, monkeypatch):
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    state = _wrap_parse(monkeypatch, log_path, lambda _n: None)
    result = verify_at_checkpoint_boundary(log_path)
    assert result.ok, result.failures
    assert result.log_size == 3
    assert state["log_reads"] == 1
    assert not any("tail_truncation_recounted" in w for w in result.warnings)


def test_o1_persistent_tear_still_fails_as_truncation(tmp_path, monkeypatch):
    """A writer that stays ahead on EVERY read is indistinguishable
    from a log that never reaches its checkpoint: the mismatch
    persists across the recount and the verdict stays truncation."""
    log_path = tmp_path / "audit-log.jsonl"
    log = _agent_log(log_path, 3)

    def writer_always_moves(read_number: int) -> None:
        _record_segment(log, 2 + read_number)

    state = _wrap_parse(monkeypatch, log_path, writer_always_moves)
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any(f.startswith("tail_truncation") for f in result.failures)
    assert state["log_reads"] == 2  # attempt + the one recount, no more


# ------------------------------------- the guards: the cure narrows
# the false positive only; real breakage still fails.
def test_o1_genuine_tail_truncation_still_fails(tmp_path):
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    log_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any(f.startswith("tail_truncation") for f in result.failures)


def test_o1_genuine_mid_chain_corruption_still_fails(tmp_path):
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert '"segment 1"' in lines[1]
    lines[1] = lines[1].replace('"segment 1"', '"segment X"')
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any(
        "chain_broken" in failure or "entry_hash" in failure
        for failure in result.failures
    ), result.failures


def test_o1_recount_does_not_launder_corruption(tmp_path, monkeypatch):
    """Tear + genuine corruption together: the recount judges the
    fresh pair in full, so the corrupted committed prefix still
    fails — the recount is a re-read, not an amnesty."""
    log_path = tmp_path / "audit-log.jsonl"
    log = _agent_log(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert '"segment 1"' in lines[1]
    lines[1] = lines[1].replace('"segment 1"', '"segment X"')
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def writer_moves_once(read_number: int) -> None:
        if read_number == 1:
            _record_segment(log, 3)

    _wrap_parse(monkeypatch, log_path, writer_moves_once)
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any(
        "chain_broken" in failure or "entry_hash" in failure
        for failure in result.failures
    ), result.failures
