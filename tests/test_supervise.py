"""Tier A supervision (the KEEP office) — unit + fault-injection tests.

The two subprocess tests at the bottom are the feature's ship gate:
a supervised agent killed mid-work must be detected, its chain
verified, and its work resumed to completion; an agent whose chain
was corrupted must be REFUSED — halted and escalated, never resumed.
"""

import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import chancellor
from chancellor.cli import main as cli_main
from chancellor.escalation import (
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
)
from chancellor.supervise import (
    CAUSE_PLAUSIBLE,
    CAUSE_PROVEN,
    CAUSE_UNKNOWN,
    CheckpointSnapshot,
    Supervisor,
    SupervisorConfig,
    WatchVerdict,
    discriminate,
    grade_cause,
    rebuild_supervision_state,
    verify_at_checkpoint_boundary,
)
from chancellor.verify_log import verify_log

SRC = str(Path(chancellor.__file__).resolve().parent.parent)


# ---------------------------------------------------------------- helpers
def _agent_log(path: Path, segments: int) -> AuditLog:
    """An agent's governed record: `segments` receipts, each sealed
    with a signed checkpoint as it lands."""
    log = AuditLog(path)
    for i in range(segments):
        request = EscalationRequest(
            action="segment",
            action_class=ActionClass.COMPUTE,
            detail=f"segment {i}",
        )
        log.record(Decision(request, True, "agent", "committed", time.time()))
        log.checkpoint()
    return log


def _events(log_path: Path) -> list[dict]:
    """The supervision record's events, decoded from receipt details."""
    events = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        try:
            detail = json.loads(entry.get("detail") or "{}")
        except json.JSONDecodeError:
            detail = {}
        events.append({"entry": entry, "detail": detail, "event": detail.get("event")})
    return events


class _FakeHandle:
    """A scripted process double: poll() returns the script's values
    in order, then stays alive (None) forever."""

    def __init__(self, script: list[int | None]):
        self._script = list(script)
        self.pid = 4242
        self.terminated = False

    def poll(self) -> int | None:
        if self._script:
            return self._script.pop(0)
        return None

    def terminate(self) -> None:
        self.terminated = True


class _FakeLauncher:
    def __init__(self, handles: list[_FakeHandle]):
        self._handles = list(handles)
        self.calls: list[list[str]] = []

    def __call__(self, command: list[str]) -> _FakeHandle:
        self.calls.append(command)
        return self._handles.pop(0)


def _config(tmp_path: Path, **overrides) -> SupervisorConfig:
    config = SupervisorConfig(
        agent_command=[sys.executable, "-c", "pass"],
        state_dir=tmp_path,
        cadence_s=1.0,
        missed=3,
        poll_s=0.01,
        heartbeat_s=10_000.0,
    )
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _supervisor(
    tmp_path: Path,
    launcher,
    snapshot_fn,
    *,
    clock=None,
    emitted: list[str] | None = None,
    **overrides,
) -> Supervisor:
    return Supervisor(
        _config(tmp_path, **overrides),
        clock=clock or (lambda: 1_000.0),
        sleeper=lambda _s: None,
        launcher=launcher,
        emit=emitted.append if emitted is not None else (lambda _line: None),
        snapshot_fn=snapshot_fn,
    )


def _snap(
    log_size: int, age_s: float = 1.0, written_at: float | None = None
) -> CheckpointSnapshot:
    return CheckpointSnapshot(
        log_size=log_size,
        head_hash="head",
        created_at=0,
        age_s=age_s,
        written_at=written_at,
    )


class _SnapshotSequence:
    def __init__(self, snapshots: list[CheckpointSnapshot]):
        self._snapshots = list(snapshots)

    def __call__(self) -> CheckpointSnapshot:
        if len(self._snapshots) > 1:
            return self._snapshots.pop(0)
        return self._snapshots[0]


class _Clock:
    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


# ------------------------------------------------------- cause grading
def test_grade_cause_proven_only_with_witnessed_exit_status():
    assert grade_cause(exit_status=-9, witnessed=True) == CAUSE_PROVEN
    assert grade_cause(exit_status=None, witnessed=True) == CAUSE_PLAUSIBLE
    assert grade_cause(exit_status=-9, witnessed=False) == CAUSE_PLAUSIBLE
    assert grade_cause(exit_status=None, witnessed=False) == CAUSE_UNKNOWN


# ------------------------------------------------------ discrimination
def test_discriminate_exit_status_is_decisive():
    assert (
        discriminate(
            process_alive=False,
            exit_status=0,
            checkpoint_age_s=0.0,
            stale_threshold_s=3.0,
        )
        is WatchVerdict.COMPLETED
    )
    # Death is DOWN immediately — no staleness wait for a witnessed exit.
    assert (
        discriminate(
            process_alive=False,
            exit_status=-9,
            checkpoint_age_s=0.0,
            stale_threshold_s=3.0,
        )
        is WatchVerdict.DOWN
    )


def test_discriminate_stale_but_alive_is_stalled_never_down():
    assert (
        discriminate(
            process_alive=True,
            exit_status=None,
            checkpoint_age_s=10.0,
            stale_threshold_s=3.0,
        )
        is WatchVerdict.STALLED
    )
    assert (
        discriminate(
            process_alive=True,
            exit_status=None,
            checkpoint_age_s=1.0,
            stale_threshold_s=3.0,
        )
        is WatchVerdict.HEALTHY
    )
    assert (
        discriminate(
            process_alive=False,
            exit_status=None,
            checkpoint_age_s=1.0,
            stale_threshold_s=3.0,
        )
        is WatchVerdict.DOWN
    )


# ------------------------------------------- boundary verification
def test_verify_boundary_ok(tmp_path):
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    result = verify_at_checkpoint_boundary(log_path)
    assert result.ok, result.failures
    assert result.log_size == 3
    assert result.entries_present == 3


def test_verify_boundary_detects_mid_chain_edit(tmp_path):
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


def test_verify_boundary_detects_truncation(tmp_path):
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    log_path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any("tail_truncation" in failure for failure in result.failures)


def test_verify_boundary_refuses_uncheckpointed_log(tmp_path):
    log_path = tmp_path / "audit-log.jsonl"
    log = AuditLog(log_path)
    request = EscalationRequest(
        action="segment", action_class=ActionClass.COMPUTE, detail="segment 0"
    )
    log.record(Decision(request, True, "agent", "committed", time.time()))
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any("no_signed_checkpoint" in failure for failure in result.failures)


def test_verify_boundary_rejects_forged_checkpoint(tmp_path):
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 2)
    cp_path = Path(str(log_path) + ".checkpoints.jsonl")
    envelopes = [
        json.loads(line)
        for line in cp_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    payload = json.loads(base64.b64decode(envelopes[-1]["payload"]).decode("utf-8"))
    payload["log_size"] = 99  # forge the committed size; signature now stale
    envelopes[-1]["payload"] = base64.b64encode(
        json.dumps(payload).encode("utf-8")
    ).decode("ascii")
    cp_path.write_text(
        "\n".join(json.dumps(e) for e in envelopes) + "\n", encoding="utf-8"
    )
    result = verify_at_checkpoint_boundary(log_path)
    assert not result.ok
    assert any("checkpoint_signature_invalid" in failure for failure in result.failures)


# ------------------------------------------------------ state rebuild
def test_rebuild_supervision_state_survives_restart():
    def entry(event: str, **detail) -> dict:
        return {"detail": json.dumps({"event": event, **detail})}

    entries = [
        entry("supervision_started"),
        entry("interruption_detected", entries_at_loss=3),
        entry("resume_failed"),
        entry("resume_failed"),
        entry("resume_confirmed", agent_log_size=6),
        entry("resume_failed"),
        entry("interruption_detected", entries_at_loss=6),
    ]
    state = rebuild_supervision_state(entries)
    assert state.consecutive_failures == 1  # reset by the confirmation
    assert state.interruptions == 2
    assert state.open_watch is True
    assert state.last_agent_log_size == 6

    closed = rebuild_supervision_state(entries + [entry("escalation")])
    assert closed.escalations == 1
    assert closed.open_watch is False


# --------------------------------------------------------- self-proof
def test_self_proof_refuses_unlaunchable_command(tmp_path):
    launcher = _FakeLauncher([])
    supervisor = Supervisor(
        SupervisorConfig(
            agent_command=["/nonexistent/chancellor-test-binary"],
            state_dir=tmp_path,
        ),
        launcher=launcher,
        emit=lambda _line: None,
    )
    assert supervisor.run() == 2
    assert launcher.calls == []  # never launched under a false promise


def test_self_proof_refuses_corrupt_supervision_log(tmp_path):
    log_path = tmp_path / "supervision-log.jsonl"
    log = AuditLog(log_path)
    request = EscalationRequest(
        action="segment", action_class=ActionClass.COMPUTE, detail="x"
    )
    log.record(Decision(request, True, "agent", "ok", time.time()))
    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"segment"', '"segmenX"').replace('"x"', '"y"')
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    emitted: list[str] = []
    supervisor = Supervisor(
        _config(tmp_path),
        launcher=_FakeLauncher([]),
        emit=emitted.append,
    )
    assert supervisor.run() == 2
    assert any("persist leg failed" in line for line in emitted)


# ------------------------------------------- supervisor loop, doubled (R2/R5/R8)
def test_stalled_agent_is_receipted_never_relaunched(tmp_path):
    _agent_log(tmp_path / "audit-log.jsonl", 3)
    handle = _FakeHandle([None, None, None, 0])
    launcher = _FakeLauncher([handle])
    supervisor = _supervisor(tmp_path, launcher, lambda: _snap(3, age_s=10.0))
    assert supervisor.run() == 0
    assert len(launcher.calls) == 1  # no second copy, ever
    events = _events(tmp_path / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert "stall_anomaly" in kinds
    assert "agent_completed" in kinds


def test_cadence_advisory_fires_once_on_slow_consecutive_checkpoints(tmp_path):
    _agent_log(tmp_path / "audit-log.jsonl", 5)
    handle = _FakeHandle([None, None, None, 0])
    launcher = _FakeLauncher([handle])
    emitted: list[str] = []
    snapshots = _SnapshotSequence(
        [
            _snap(3, written_at=100.0),
            _snap(4, written_at=105.0),
            _snap(5, written_at=111.0),
            _snap(5, written_at=111.0),
        ]
    )
    supervisor = _supervisor(tmp_path, launcher, snapshots, emitted=emitted)

    assert supervisor.run() == 0
    assert len(launcher.calls) == 1
    events = _events(tmp_path / "supervision-log.jsonl")
    advisories = [e for e in events if e["event"] == "cadence_advisory"]
    assert len(advisories) == 1
    detail = advisories[0]["detail"]
    assert detail["basis"] == "consecutive_checkpoints"
    assert detail["observed_checkpoint_interval_s"] == 5.0
    assert detail["cadence_s"] == 1.0
    assert detail["missed"] == 3
    assert detail["stale_threshold_s"] == 3.0
    assert detail["advisory_only"] is True
    assert "escalation" not in [e["event"] for e in events]
    assert any(
        "CADENCE ADVISORY" in line
        and "observed signed-checkpoint interval 5.0s" in line
        for line in emitted
    )


def test_cadence_advisory_fires_for_fresh_start_without_checkpoint(tmp_path):
    handle = _FakeHandle([None, None, 0])
    launcher = _FakeLauncher([handle])
    emitted: list[str] = []
    clock = _Clock()
    calls = {"n": 0}

    def snapshot() -> None:
        calls["n"] += 1
        clock.now = 1_003.0 if calls["n"] == 1 else 1_004.0
        return

    supervisor = _supervisor(tmp_path, launcher, snapshot, clock=clock, emitted=emitted)

    assert supervisor.run() == 0
    events = _events(tmp_path / "supervision-log.jsonl")
    advisories = [e for e in events if e["event"] == "cadence_advisory"]
    assert len(advisories) == 1
    detail = advisories[0]["detail"]
    assert detail["basis"] == "fresh_start_no_checkpoint"
    assert detail["observed_no_checkpoint_after_s"] == 3.0
    assert detail["agent_log_size"] is None
    assert "escalation" not in [e["event"] for e in events]
    assert any("no signed checkpoint after 3.0s" in line for line in emitted)


def test_cadence_advisory_does_not_fire_on_matched_cadence(tmp_path):
    _agent_log(tmp_path / "audit-log.jsonl", 4)
    handle = _FakeHandle([None, None, 0])
    launcher = _FakeLauncher([handle])
    snapshots = _SnapshotSequence(
        [
            _snap(3, written_at=100.0),
            _snap(4, written_at=102.0),
            _snap(4, written_at=102.0),
        ]
    )
    supervisor = _supervisor(tmp_path, launcher, snapshots)

    assert supervisor.run() == 0
    events = _events(tmp_path / "supervision-log.jsonl")
    assert "cadence_advisory" not in [e["event"] for e in events]
    assert "agent_completed" in [e["event"] for e in events]


def test_cadence_advisory_latches_across_resume_and_resume_confirms(tmp_path):
    _agent_log(tmp_path / "audit-log.jsonl", 3)
    first = _FakeHandle([-9])
    second = _FakeHandle([None, 0])
    launcher = _FakeLauncher([first, second])
    snapshots = _SnapshotSequence(
        [
            _snap(3, written_at=100.0),
            _snap(4, written_at=105.0),
            _snap(5, written_at=111.0),
        ]
    )
    supervisor = _supervisor(tmp_path, launcher, snapshots)

    assert supervisor.run() == 0
    assert len(launcher.calls) == 2
    events = _events(tmp_path / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert kinds.count("cadence_advisory") == 1
    assert "resume_launched" in kinds
    assert "resume_confirmed" in kinds
    assert "agent_completed" in kinds
    assert "escalation" not in kinds


def test_supervise_help_names_cadence_guidance(capsys):
    assert cli_main(["supervise", "--help"]) == 0
    captured = capsys.readouterr()
    assert "--cadence" in captured.out
    assert "docs/supervision-cadence.md" in captured.out


def test_resume_budget_exhausts_and_escalates(tmp_path):
    _agent_log(tmp_path / "audit-log.jsonl", 3)
    handles = [_FakeHandle([-9]) for _ in range(4)]
    launcher = _FakeLauncher(handles)
    supervisor = _supervisor(tmp_path, launcher, lambda: _snap(3), budget=3)
    assert supervisor.run() == 1
    assert len(launcher.calls) == 4  # initial + exactly N=3 resumes
    events = _events(tmp_path / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert kinds.count("resume_failed") == 3
    assert "budget_exhausted" in kinds
    assert "escalation" in kinds
    interruption = next(e for e in events if e["event"] == "interruption_detected")
    assert interruption["detail"]["cause"] == CAUSE_PROVEN
    assert interruption["detail"]["exit_status"] == -9


def test_live_drift_halts_and_escalates(tmp_path):
    """R7, deterministic: the agent's boundary moves to a state that
    no longer verifies while the agent lives — the supervisor halts
    the agent itself and escalates, after exactly the one detection."""
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    handle = _FakeHandle([None, None, None])
    launcher = _FakeLauncher([handle])
    calls = {"n": 0}

    def snapshot() -> CheckpointSnapshot:
        calls["n"] += 1
        if calls["n"] >= 2:
            # History is rewritten under the live agent; the next
            # boundary the agent seals no longer verifies.
            lines = log_path.read_text(encoding="utf-8").splitlines()
            lines[1] = lines[1].replace('"segment 1"', '"segment X"')
            log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return _snap(4)
        return _snap(3)

    supervisor = _supervisor(tmp_path, launcher, snapshot)
    assert supervisor.run() == 1
    assert handle.terminated is True
    events = _events(tmp_path / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert "drift_detected" in kinds
    assert "escalation" in kinds
    assert "resume_launched" not in kinds


def test_existing_broken_chain_refused_at_start(tmp_path):
    """R3 at the first launch: existing state that does not verify is
    never launched onto — refusal and escalation before any agent runs."""
    log_path = tmp_path / "audit-log.jsonl"
    _agent_log(log_path, 3)
    lines = log_path.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"segment 0"', '"segment Y"')
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    launcher = _FakeLauncher([])
    supervisor = _supervisor(tmp_path, launcher, lambda: _snap(3))
    assert supervisor.run() == 1
    assert launcher.calls == []
    events = _events(tmp_path / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert "chain_verification" in kinds
    assert "escalation" in kinds


def test_resume_confirms_when_chain_advances(tmp_path):
    _agent_log(tmp_path / "audit-log.jsonl", 3)
    first = _FakeHandle([-9])
    second = _FakeHandle([None, 0])
    launcher = _FakeLauncher([first, second])

    def snapshot() -> CheckpointSnapshot:
        # After the relaunch, the agent's chain advances past the loss.
        return _snap(4 if len(launcher.calls) >= 2 else 3)

    supervisor = _supervisor(tmp_path, launcher, snapshot)
    assert supervisor.run() == 0
    assert len(launcher.calls) == 2
    events = _events(tmp_path / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert "resume_confirmed" in kinds
    assert "agent_completed" in kinds
    state = rebuild_supervision_state([e["entry"] for e in events])
    assert state.consecutive_failures == 0
    assert state.interruptions == 1


# ======================================================================
# FAULT INJECTION — the ship gate. Real processes, real kills.
# ======================================================================
AGENT = r"""
import os, sys, time
from pathlib import Path

from chancellor.escalation import (
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
)

log_path = Path(sys.argv[1])
total = int(sys.argv[2])
interval = float(sys.argv[3])
pidfile = Path(sys.argv[4])
pidfile.write_text(str(os.getpid()))
log = AuditLog(log_path)
done = sum(1 for e in log.read_all() if e["action"] == "segment")
while done < total:
    request = EscalationRequest(
        action="segment",
        action_class=ActionClass.COMPUTE,
        detail=f"segment {done}",
    )
    log.record(Decision(request, True, "agent", "segment committed", time.time()))
    log.checkpoint()
    done += 1
    if done < total:
        time.sleep(interval)
"""


def _spawn_supervisor(
    tmp_path: Path, agent_log: Path, total: int, interval: float
) -> tuple[subprocess.Popen, Path, Path]:
    state_dir = tmp_path / "state"
    agent_py = tmp_path / "agent.py"
    agent_py.write_text(AGENT, encoding="utf-8")
    pidfile = tmp_path / "agent.pid"
    env = dict(os.environ, PYTHONPATH=SRC)
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "chancellor.cli",
            "supervise",
            "--state-dir",
            str(state_dir),
            "--cadence",
            "0.2",
            "--missed",
            "3",
            "--poll",
            "0.05",
            "--heartbeat",
            "2",
            "--",
            sys.executable,
            str(agent_py),
            str(agent_log),
            str(total),
            str(interval),
            str(pidfile),
        ],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc, state_dir, pidfile


def _wait_until(predicate, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _checkpoint_count(agent_log: Path) -> int:
    cp_path = Path(str(agent_log) + ".checkpoints.jsonl")
    if not cp_path.exists():
        return 0
    lines = cp_path.read_text(encoding="utf-8").splitlines()
    return len([line for line in lines if line.strip()])


def _segment_count(agent_log: Path) -> int:
    if not agent_log.exists():
        return 0
    return sum(
        1
        for line in agent_log.read_text(encoding="utf-8").splitlines()
        if '"action": "segment"' in line
    )


def test_fault_injection_kill_verify_resume(tmp_path):
    """SHIP GATE 1: SIGKILL a supervised agent mid-work. The supervisor
    must detect the death, verify the chain, resume the agent, and the
    agent must complete every segment exactly once, chain intact."""
    agent_log = tmp_path / "state" / "audit-log.jsonl"
    # 40 segments: the kill window (segments ~4..39) is far wider than
    # any test-harness latency, so the kill always lands mid-work.
    proc, state_dir, pidfile = _spawn_supervisor(tmp_path, agent_log, 40, 0.15)
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3), (
            "agent never reached 3 checkpoints"
        )
        assert _wait_until(lambda: pidfile.exists())
        agent_pid = int(pidfile.read_text(encoding="utf-8"))
        # Kill on a fresh commit boundary: the agent has just sealed a
        # checkpoint and is entering its sleep, not mid-write.
        committed = _checkpoint_count(agent_log)
        assert _wait_until(lambda: _checkpoint_count(agent_log) > committed)
        os.kill(agent_pid, signal.SIGKILL)
        out, _err = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 0, f"supervisor exited {proc.returncode}:\n{out}"
    assert _segment_count(agent_log) == 40

    # The agent's chain verifies cold, end to end.
    result = verify_log(agent_log)
    assert result.ok, result.failures
    seqs = [e["seq"] for e in AuditLog(agent_log).read_all()]
    assert seqs == list(range(len(seqs)))

    # The supervision record tells the whole story, honestly graded.
    events = _events(state_dir / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    assert "interruption_detected" in kinds
    interruption = next(e for e in events if e["event"] == "interruption_detected")
    assert interruption["detail"]["cause"] == CAUSE_PROVEN
    assert interruption["detail"]["exit_status"] == -signal.SIGKILL
    verification = next(e for e in events if e["event"] == "chain_verification")
    assert verification["detail"]["ok"] is True
    assert "resume_launched" in kinds
    assert "agent_completed" in kinds
    assert verify_log(state_dir / "supervision-log.jsonl").ok


def test_fault_injection_corrupt_chain_refused_and_escalated(tmp_path):
    """SHIP GATE 2: corrupt one entry mid-chain, then kill the agent.
    The supervisor must refuse the resume, halt, and escalate — the
    agent must NOT run again."""
    agent_log = tmp_path / "state" / "audit-log.jsonl"
    proc, state_dir, pidfile = _spawn_supervisor(tmp_path, agent_log, 100, 0.15)
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3), (
            "agent never reached 3 checkpoints"
        )
        assert _wait_until(lambda: pidfile.exists())
        agent_pid = int(pidfile.read_text(encoding="utf-8"))
        committed = _checkpoint_count(agent_log)
        assert _wait_until(lambda: _checkpoint_count(agent_log) > committed)
        pidfile_stat = pidfile.stat().st_mtime_ns

        # Corrupt one byte of history: an early entry's content no
        # longer matches its hash. JSON stays valid; the chain breaks.
        lines = agent_log.read_text(encoding="utf-8").splitlines()
        assert '"segment 1"' in lines[1]
        lines[1] = lines[1].replace('"segment 1"', '"segment X"')
        agent_log.write_text("\n".join(lines) + "\n", encoding="utf-8")

        segments_at_kill = _segment_count(agent_log)
        os.kill(agent_pid, signal.SIGKILL)
        out, _err = proc.communicate(timeout=120)
    finally:
        if proc.poll() is None:
            proc.kill()
    assert proc.returncode == 1, f"supervisor exited {proc.returncode}:\n{out}"

    # No resume happened: the pidfile was never rewritten by a new
    # lifetime, and the segment count is frozen at the kill.
    assert pidfile.read_text(encoding="utf-8") == str(agent_pid)
    assert pidfile.stat().st_mtime_ns == pidfile_stat
    assert _segment_count(agent_log) <= segments_at_kill + 1
    time.sleep(1.0)
    assert _segment_count(agent_log) <= segments_at_kill + 1

    events = _events(state_dir / "supervision-log.jsonl")
    kinds = [e["event"] for e in events]
    # Two governed refusal paths are legitimate, and which one fires
    # is a race the record itself settles:
    #  (a) the kill lands first — death, then chain_verification
    #      ok=False, resume refused, escalation;
    #  (b) the supervisor's live drift check (R7) sees the moved
    #      boundary first — drift_detected with failures, the agent
    #      halted by the supervisor, escalation.
    # Both must end the same way: exit 1, escalation receipted, a
    # verification failure on record, and NO resume. Those invariants
    # are the ship gate; the path is the record's business.
    assert "escalation" in kinds
    assert "resume_launched" not in kinds
    refused_at_resume = any(
        e["event"] == "chain_verification" and e["detail"].get("ok") is False
        for e in events
    )
    refused_live = any(
        e["event"] == "drift_detected" and e["detail"].get("failures") for e in events
    )
    assert refused_at_resume or refused_live, (
        f"no verification-refusal record in {kinds}"
    )
    assert verify_log(state_dir / "supervision-log.jsonl").ok
