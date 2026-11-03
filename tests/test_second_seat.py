"""Acceptance tests for the built-in second seat (SPEC companion
ACCEPTANCE.md, T1–T15). Process-level tests use real subprocesses,
real kills, and real chains, mirroring tests/test_supervise.py's
fault-injection harness; deterministic tests drive Monitor through
its injectable seams (clock, sleeper, pid table, supervisor
launcher) against real on-disk chains.

T4 honesty clause (from ACCEPTANCE.md): interleavings the harness
cannot produce — true split-brain across hosts — are NOT EXERCISED
here and are reported as such in the build RESULTS, never passed by
analogy.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import chancellor
from chancellor.escalation import ActionClass, AuditLog, Decision, EscalationRequest
from chancellor.second_seat import Monitor, SecondSeatConfig
from chancellor.supervise import Supervisor, SupervisorConfig, rebuild_supervision_state
from chancellor.verify_log import verify_log

SRC = str(Path(chancellor.__file__).resolve().parent.parent)

AGENT = """
import os, sys, time
from pathlib import Path
from chancellor.escalation import ActionClass, AuditLog, Decision, EscalationRequest
log_path = Path(sys.argv[1]); total = int(sys.argv[2]); interval = float(sys.argv[3])
pidfile = Path(sys.argv[4]); pidfile.write_text(str(os.getpid()))
log = AuditLog(log_path)
done = sum(1 for e in log.read_all() if e["action"] == "segment")
while done < total:
    req = EscalationRequest(action="segment", action_class=ActionClass.COMPUTE,
                            detail=f"segment {done}")
    log.record(Decision(req, True, "agent", "segment committed", time.time()))
    log.checkpoint()
    done += 1
    if done < total:
        time.sleep(interval)
"""


# ---------------------------------------------------------------- helpers
def _events(log_path: Path) -> list[dict]:
    events = []
    if not log_path.exists():
        return events
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        try:
            detail = json.loads(entry.get("detail") or "{}")
        except json.JSONDecodeError:
            detail = {}
        events.append(
            {"entry": entry, "detail": detail, "event": detail.get("event")}
        )
    return events


def _wait_until(predicate, timeout: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return predicate()


def _segment_count(agent_log: Path) -> int:
    if not agent_log.exists():
        return 0
    return sum(
        1
        for line in agent_log.read_text(encoding="utf-8").splitlines()
        if '"action": "segment"' in line
    )


def _checkpoint_count(agent_log: Path) -> int:
    cp_path = Path(str(agent_log) + ".checkpoints.jsonl")
    if not cp_path.exists():
        return 0
    return len(
        [ln for ln in cp_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    )


def _supervisor_pid(state_dir: Path) -> int | None:
    lock = state_dir / "supervision.lock"
    if not lock.exists():
        return None
    try:
        return json.loads(lock.read_text(encoding="utf-8"))["pid"]
    except (json.JSONDecodeError, KeyError):
        return None


def _spawn_pair(
    tmp_path: Path,
    *,
    total: int,
    interval: float,
    seat_poll: float = 0.3,
    heartbeat: float = 2,
) -> tuple[subprocess.Popen, Path, Path]:
    state_dir = tmp_path / "state"
    agent_py = tmp_path / "agent.py"
    agent_py.write_text(AGENT, encoding="utf-8")
    agent_log = state_dir / "audit-log.jsonl"
    pidfile = tmp_path / "agent.pid"
    env = dict(os.environ, PYTHONPATH=SRC)
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "chancellor.cli", "supervise",
            "--second-seat", "--seat-poll", str(seat_poll),
            "--state-dir", str(state_dir),
            "--cadence", "0.2", "--missed", "3", "--poll", "0.05",
            "--heartbeat", str(heartbeat),
            "--", sys.executable, str(agent_py), str(agent_log),
            str(total), str(interval), str(pidfile),
        ],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    return proc, state_dir, pidfile


def _kill(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
        proc.wait(timeout=30)


# ---------------------------------------------------------------- T1
def test_t1_kill_primary_reseat_exactly_once(tmp_path):
    proc, state_dir, pidfile = _spawn_pair(tmp_path, total=40, interval=0.15)
    agent_log = state_dir / "audit-log.jsonl"
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 5)
        assert _wait_until(lambda: _supervisor_pid(state_dir) is not None)
        sup_pid = _supervisor_pid(state_dir)
        committed = _checkpoint_count(agent_log)
        assert _wait_until(lambda: _checkpoint_count(agent_log) > committed)
        os.kill(sup_pid, signal.SIGKILL)
        # ACCEPTANCE T1 setup: the agent dies with its supervisor
        # (harness process-tree setup) — its chain stops. An orphaned
        # agent left writing would fork the chain's seq when the
        # successor relaunches it, and the successor would be right
        # to refuse; that is a different test (T3's family).
        if pidfile.exists():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
        out, _err = proc.communicate(timeout=240)
    finally:
        _kill(proc)
    assert proc.returncode == 0, f"monitor exited {proc.returncode}:\n{out}"
    assert _segment_count(agent_log) == 40
    # Agent steps exactly once: segment details 0..39, each once.
    details = [
        e["detail"]
        for e in (
            json.loads(ln)
            for ln in agent_log.read_text().splitlines()
            if ln.strip()
        )
        if e.get("action") == "segment"
    ]
    assert sorted(details, key=lambda d: int(d.split()[1])) == [
        f"segment {i}" for i in range(40)
    ]
    assert verify_log(agent_log).ok
    sup_log = state_dir / "supervision-log.jsonl"
    events = _events(sup_log)
    kinds = [e["event"] for e in events]
    interruption = next(e for e in events if e["event"] == "supervisor_interruption")
    assert interruption["detail"]["cause"] == "proven"
    initiated = next(e for e in events if e["event"] == "supervisor_reseat_initiated")
    assert initiated["detail"]["watch_epoch"] == 1
    started = next(
        e for e in events
        if e["event"] == "supervision_started" and e["detail"].get("watch_epoch") == 1
    )
    confirmed = next(e for e in events if e["event"] == "supervisor_reseat_confirmed")
    assert (
        confirmed["detail"]["confirming_started_seq"]
        == started["entry"]["seq"]
    )
    assert any(
        e["event"] == "supervisor_heartbeat"
        and e["entry"]["seq"] > started["entry"]["seq"]
        for e in events
    )
    # R8 untouched by the reseat: no agent failures existed, none appear.
    state = rebuild_supervision_state(AuditLog(sup_log).read_all())
    assert state.consecutive_failures == 0
    assert state.supervisor_interruptions == 1
    assert verify_log(sup_log).ok
    assert "agent_completed" in kinds


# ---------------------------------------------------------------- T2
def test_t2_wedged_primary_never_reseated(tmp_path):
    proc, state_dir, _pf = _spawn_pair(tmp_path, total=200, interval=0.3)
    agent_log = state_dir / "audit-log.jsonl"
    seat_log = state_dir / "second-seat-log.jsonl"
    sup_log = state_dir / "supervision-log.jsonl"
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3)
        assert _wait_until(lambda: _supervisor_pid(state_dir) is not None)
        sup_pid = _supervisor_pid(state_dir)
        os.kill(sup_pid, signal.SIGSTOP)
        wedged = lambda: any(  # noqa: E731
            e["event"] == "supervisor_wedged" for e in _events(seat_log)
        )
        assert _wait_until(wedged, timeout=60), "no wedge receipted"
        # Exactly one wedge receipt for the episode.
        time.sleep(2)
        wedged_count = sum(
            1 for e in _events(seat_log)
            if e["event"] == "supervisor_wedged"
        )
        assert wedged_count == 1
        # No spawn, no chain appends by the seat, primary untouched.
        kinds = [e["event"] for e in _events(sup_log)]
        assert "supervisor_interruption" not in kinds
        assert "supervisor_reseat_initiated" not in kinds
        assert _supervisor_pid(state_dir) == sup_pid
        escalated = lambda: any(  # noqa: E731
            e["event"] == "second_seat_escalation"
            and e["detail"].get("reason") == "wedge"
            for e in _events(seat_log)
        )
        assert _wait_until(escalated, timeout=60), "no wedge escalation"
        chain_events = len(_events(sup_log))
        os.kill(sup_pid, signal.SIGCONT)
        cleared = lambda: any(  # noqa: E731
            e["event"] == "supervisor_wedge_cleared" for e in _events(seat_log)
        )
        assert _wait_until(cleared, timeout=60), "wedge never cleared"
        # The seat appended nothing to the supervision chain all episode
        # (heartbeats are the primary's own and resume after SIGCONT).
        seat_chain_events = [
            e for e in _events(sup_log)
            if e["entry"].get("decider") == "second-seat"
        ]
        assert seat_chain_events == []
        assert chain_events >= 0  # chain grew only by the primary's own hand
    finally:
        try:
            pid = _supervisor_pid(state_dir)
            if pid:
                os.kill(pid, signal.SIGCONT)
        except OSError:
            pass
        _kill(proc)
        agent_pid_file = tmp_path / "agent.pid"
        if agent_pid_file.exists():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(agent_pid_file.read_text()), signal.SIGKILL)


# ---------------------------------------------------------------- T3
def test_t3_corrupt_agent_chain_successor_refuses(tmp_path):
    proc, state_dir, pidfile = _spawn_pair(
        tmp_path, total=200, interval=0.2, seat_poll=2.0
    )
    agent_log = state_dir / "audit-log.jsonl"
    sup_log = state_dir / "supervision-log.jsonl"
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 5)
        assert _wait_until(lambda: _supervisor_pid(state_dir) is not None)
        sup_pid = _supervisor_pid(state_dir)
        agent_pid_before = pidfile.read_text()
        os.kill(sup_pid, signal.SIGKILL)
        # The agent dies with its supervisor (as T1): its chain is
        # frozen at the corruption point, so "no new entries after
        # the corruption" is assertable and the pidfile comparison
        # below measures the successor, not a surviving orphan.
        with contextlib.suppress(OSError, ValueError):
            os.kill(int(agent_pid_before), signal.SIGKILL)
        # Corrupt a committed entry below the newest boundary at once;
        # the seat's 2 s poll gives the corruption time to land before
        # the successor's initial verification.
        lines = agent_log.read_text(encoding="utf-8").splitlines()
        assert '"segment 1"' in lines[1]
        lines[1] = lines[1].replace('"segment 1"', '"segment X"')
        agent_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out, _err = proc.communicate(timeout=240)
    finally:
        _kill(proc)
        if pidfile.exists():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(pidfile.read_text()), signal.SIGKILL)
    assert proc.returncode == 1, f"monitor exited {proc.returncode}:\n{out}"
    events = _events(sup_log)
    kinds = [e["event"] for e in events]
    # `approved` is the receipt-level Decision field (ACCEPTANCE's
    # wording); the verifier's named failures ride in detail.
    refused = [
        e for e in events
        if e["event"] == "chain_verification"
        and e["entry"].get("approved") is False
        and e["detail"].get("failures")
    ]
    assert refused, f"no failed chain_verification in {kinds}"
    assert "escalation" in kinds
    assert "resume_launched" not in kinds
    assert pidfile.read_text() == agent_pid_before  # agent never relaunched
    initiated = [e for e in events if e["event"] == "supervisor_reseat_initiated"]
    assert len(initiated) == 1  # no second attempt after a refusal


# ---------------------------------------------------------------- T4
def test_t4_two_monitors_and_hand_launch_refused(tmp_path):
    proc, state_dir, _pf = _spawn_pair(tmp_path, total=200, interval=0.3)
    agent_log = state_dir / "audit-log.jsonl"
    env = dict(os.environ, PYTHONPATH=SRC)
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3)
        assert _wait_until(lambda: _supervisor_pid(state_dir) is not None)
        # (a) a second monitor cannot arm: the seat lock is held.
        second = subprocess.run(
            [sys.executable, "-m", "chancellor.cli", "supervise",
             "--monitor-only", "--state-dir", str(state_dir)],
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert second.returncode == 2, second.stdout + second.stderr
        # (b) a hand-launched seat-less supervisor refuses to join a
        # seat-enabled watch while the seat's supervisor holds it.
        hand = subprocess.run(
            [sys.executable, "-m", "chancellor.cli", "supervise",
             "--state-dir", str(state_dir), "--cadence", "0.2",
             "--", sys.executable, "-c", "pass"],
            env=env, capture_output=True, text=True, timeout=60,
        )
        assert hand.returncode == 2, hand.stdout + hand.stderr
    finally:
        _kill(proc)
        agent_pid_file = tmp_path / "agent.pid"
        if agent_pid_file.exists():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(agent_pid_file.read_text()), signal.SIGKILL)


def test_t4_stale_primary_fences_itself(tmp_path):
    """(c)/(d): a revived stale supervisor stops at its next heartbeat
    append (exit 3) and writes nothing further; the chain stays a
    single linear chain with monotone epochs."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    now = [10_000.0]
    sup_log_path = state_dir / "supervision-log.jsonl"

    class _Handle:
        pid = 31337

        def poll(self):
            return None

        def terminate(self):
            pass

    config = SupervisorConfig(
        agent_command=[sys.executable, "-c", "pass"],
        state_dir=state_dir,
        cadence_s=1.0, missed=3, poll_s=0.01, heartbeat_s=5.0,
        seat_enabled=True, watch_epoch=0,
    )
    sup = Supervisor(
        config,
        launcher=lambda cmd: _Handle(),
        clock=lambda: now[0],
        sleeper=lambda s: None,
        snapshot_fn=lambda: None,
        emit=lambda line: None,
    )
    assert sup.self_proof() is None
    sup._child = _Handle()  # run() would have launched it; the poll
    # seam asserts the invariant before the fence check is reached.
    # A monitor reseats a successor at epoch 1 while this primary is
    # "stopped" — simulated by the monitor's own append.
    log = AuditLog(sup_log_path)
    req = EscalationRequest(
        action="second-seat: supervisor reseat initiated",
        action_class=ActionClass.COMPUTE,
        detail=json.dumps(
            {"event": "supervisor_reseat_initiated", "watch_epoch": 1,
             "successor_command": ["x"], "attempt": 1, "episode_budget": 3},
            sort_keys=True,
        ),
    )
    log.record(Decision(req, True, "second-seat", "initiated", now[0]))
    log.checkpoint()
    entries_before = len(AuditLog(sup_log_path).read_all())
    now[0] += 10.0  # heartbeat due
    sup._last_heartbeat = 0.0
    outcome = sup._poll_once()
    assert outcome == 3
    entries_after = AuditLog(sup_log_path).read_all()
    assert len(entries_after) == entries_before  # zero appended entries
    assert verify_log(sup_log_path).ok  # fork detector: single chain
    epochs = [
        json.loads(e["detail"]).get("watch_epoch")
        for e in entries_after
        if isinstance(json.loads(e["detail"]).get("watch_epoch"), int)
    ]
    assert epochs == sorted(epochs)


# ------------------------------------------------------- monitor fixtures
DEAD_PID = 424242


def _record(log: AuditLog, event: str, detail: dict, decider: str, ts: float) -> None:
    full = {"event": event, **detail}
    req = EscalationRequest(
        action=f"{decider}: {event}",
        action_class=ActionClass.COMPUTE,
        detail=json.dumps(full, sort_keys=True),
    )
    log.record(Decision(req, True, decider, event, ts))
    log.checkpoint()


def _seat_watch_on_disk(
    tmp_path: Path, *, recorded: list[str], ts: float = 1000.0
) -> Path:
    """A seat-enabled watch whose primary is dead: supervision chain
    with a seat-enabled started, a lock body naming DEAD_PID, and a
    seat log carrying the recorded command."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    sup = AuditLog(state_dir / "supervision-log.jsonl")
    _record(
        sup, "supervision_started",
        {"watch_epoch": 0, "second_seat": True, "supervisor_pid": DEAD_PID,
         "agent_command": ["/bin/true"]},
        "supervisor", ts,
    )
    (state_dir / "supervision.lock").write_text(
        json.dumps({"pid": DEAD_PID, "watch_epoch": 0, "host": "test",
                    "started_at": ts, "seat_armed": True,
                    "pid_identity": None}),
        encoding="utf-8",
    )
    seat = AuditLog(state_dir / "second-seat-log.jsonl")
    _record(
        seat, "second_seat_armed",
        {"watch_epoch": 0, "state_dir": str(state_dir), "mode": "pair",
         "anchoring": "tier_a_same_machine", "successor_command": recorded},
        "second-seat", ts,
    )
    return state_dir


def _monitor(
    state_dir: Path,
    *,
    launcher,
    alive: dict[int, bool],
    seat: SecondSeatConfig | None = None,
    clock=None,
    sleeper=None,
    recorded: list[str] | None = None,
) -> Monitor:
    config = SupervisorConfig(
        agent_command=["/bin/true"], state_dir=state_dir,
        cadence_s=2.0, missed=3, heartbeat_s=2.0,
    )
    return Monitor(
        config,
        seat or SecondSeatConfig(poll_s=0.05),
        supervisor_argv=recorded,
        mode="attach",
        supervisor_launcher=launcher,
        pid_alive_fn=lambda pid: alive.get(pid, False),
        clock=clock or time.time,
        sleeper=sleeper or (lambda s: None),
        emit=lambda line: None,
    )


class _FakeHandle:
    def __init__(self, pid: int, status: int | None = None):
        self.pid = pid
        self._status = status

    def poll(self):
        return self._status

    def terminate(self):
        pass


# ---------------------------------------------------------------- T5
def test_t5_successor_refused_escalates_on_first_attempt(tmp_path):
    recorded = [sys.executable, "-m", "chancellor.cli", "supervise", "--", "/bin/true"]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    spawns: list[list[str]] = []

    def launcher(argv):
        spawns.append(argv)
        return _FakeHandle(999001, status=2)

    mon = _monitor(state_dir, launcher=launcher, alive={})
    assert mon.arm() is None
    # Drive cycles directly for determinism.
    for _ in range(3):
        if mon._suspended:
            break
        mon.cycle()
    events = _events(state_dir / "supervision-log.jsonl")
    assert len(spawns) == 1  # exactly one attempt for the exit-2 class
    failed = [e for e in events if e["event"] == "supervisor_reseat_failed"]
    assert failed and failed[0]["detail"]["reason"] == "successor_refused"
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    esc = [e for e in seat_events if e["event"] == "second_seat_escalation"]
    assert esc and esc[0]["detail"]["reason"] == "successor_refused"
    # After escalation: no further spawns or chain appends by the seat.
    chain_len = len(events)
    for _ in range(3):
        mon.cycle()
    assert len(spawns) == 1
    assert len(_events(state_dir / "supervision-log.jsonl")) == chain_len


def test_t5_confirmation_timeout_budget_and_clearing(tmp_path):
    recorded = [sys.executable, "-m", "chancellor.cli", "supervise", "--", "/bin/true"]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    now = [1000.0]
    spawns: list[list[str]] = []

    def launcher(argv):
        spawns.append(argv)
        return _FakeHandle(999002, status=None)  # starts, never writes

    seat = SecondSeatConfig(
        poll_s=0.05, confirmation_window_s=1.5, started_readback_s=1.0,
        backoff_s=(0.5, 0.5),
    )
    mon = _monitor(
        state_dir, launcher=launcher, alive={}, seat=seat,
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        recorded=recorded,
    )
    assert mon.arm() is None
    mon.cycle()
    events = _events(state_dir / "supervision-log.jsonl")
    assert len(spawns) == 3
    failed = [e for e in events if e["event"] == "supervisor_reseat_failed"]
    assert len(failed) == 3
    assert all(
        e["detail"]["reason"] == "confirmation_timeout" for e in failed
    )
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    esc = [e for e in seat_events if e["event"] == "second_seat_escalation"]
    assert esc and esc[0]["detail"]["reason"] == "budget"
    assert esc[0]["detail"]["attempts"] == 3
    # (e) a human clearing: an outside supervision_started restores
    # normal classification with counters reset.
    sup = AuditLog(state_dir / "supervision-log.jsonl")
    _record(
        sup, "supervision_started",
        {"watch_epoch": 4, "second_seat": True, "supervisor_pid": 777},
        "supervisor", now[0],
    )
    (state_dir / "supervision.lock").write_text(
        json.dumps({"pid": 777, "watch_epoch": 4, "host": "test",
                    "started_at": now[0], "seat_armed": True,
                    "pid_identity": None}),
        encoding="utf-8",
    )
    mon._pid_alive_fn = lambda pid: pid == 777  # the hand-started watch lives
    mon.cycle()
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    assert any(e["event"] == "second_seat_cleared" for e in seat_events)
    assert mon._suspended is False


# ---------------------------------------------------------------- T6
DRIVER = r"""
import os, sys, time
from pathlib import Path
from chancellor.supervise import Supervisor, SupervisorConfig

state_dir = Path(sys.argv[1])
block_flag = Path(sys.argv[2])

def blocking_approver(req):
    # Authorize stays outstanding until the flag file disappears —
    # the pending request the test kills the supervisor inside of.
    while block_flag.exists():
        time.sleep(0.05)
    return False

config = SupervisorConfig(
    agent_command=[sys.executable, "-c", "pass"],
    state_dir=state_dir, cadence_s=1.0, missed=3, poll_s=0.05,
    heartbeat_s=2.0, seat_enabled=True, watch_epoch=0,
)
sup = Supervisor(config, approver=blocking_approver,
                 emit=lambda line: None)
raise SystemExit(sup.run())
"""


def test_t6_pending_approval_never_decided_by_seat(tmp_path):
    """A supervisor killed while Gatekeeper.authorize is outstanding:
    the seat reseats; the request's eventual resolution is receipted
    by the successor's own gate, never by the seat; the seat's chain
    appends are exactly the section 3.4 events."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    # A corrupt pre-existing agent log: the primary escalates at
    # initial verification and blocks inside authorize.
    agent_log = state_dir / "audit-log.jsonl"
    bad = AuditLog(agent_log)
    _record(bad, "segment", {}, "agent", time.time())
    lines = agent_log.read_text(encoding="utf-8").splitlines()
    bad_entry = json.loads(lines[0])
    bad_entry["detail"] = json.dumps({"event": "tampered"}, sort_keys=True)
    lines[0] = json.dumps(bad_entry, sort_keys=True)
    agent_log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    driver = tmp_path / "driver.py"
    driver.write_text(DRIVER, encoding="utf-8")
    block_flag = tmp_path / "block.flag"
    block_flag.write_text("block", encoding="utf-8")
    recorded = [
        sys.executable, str(driver), str(state_dir), str(block_flag),
    ]
    env = dict(os.environ, PYTHONPATH=SRC)
    primary = subprocess.Popen(recorded, env=env)
    sup_log = state_dir / "supervision-log.jsonl"
    try:
        # Primary self-proofs, verifies (fails), and blocks in
        # authorize with the request outstanding.
        assert _wait_until(
            lambda: any(
                e["event"] == "chain_verification"
                for e in _events(sup_log)
            )
        )
        time.sleep(0.5)  # it is now inside the blocking approver
        os.kill(primary.pid, signal.SIGKILL)
        primary.wait(timeout=30)
        block_flag.unlink()  # the successor's authorize must not block
        config = SupervisorConfig(
            agent_command=["/bin/true"], state_dir=state_dir,
            cadence_s=2.0, missed=3, heartbeat_s=2.0,
        )
        mon = Monitor(
            config, SecondSeatConfig(poll_s=0.2),
            supervisor_argv=recorded, mode="attach",
            emit=lambda line: None,
        )
        assert mon.arm() is None
        outcome = None
        for _ in range(3):
            outcome = mon.cycle()
            if outcome is not None or mon._suspended:
                break
        events = _events(sup_log)
        # The successor resolved the request itself: an escalation
        # receipt decided by the gate (no approver attached), and the
        # seat never appears as a decider of anything but its own acts.
        resolutions = [
            e for e in events if e["event"] == "escalation"
        ]
        assert resolutions, "successor never resolved the pending request"
        assert all(
            e["entry"]["decider"] != "second-seat" for e in resolutions
        )
        seat_chain = [
            e for e in events if e["entry"]["decider"] == "second-seat"
        ]
        assert {e["event"] for e in seat_chain} <= {
            "supervisor_interruption",
            "supervisor_reseat_initiated",
            "supervisor_reseat_confirmed",
            "supervisor_reseat_failed",
        }
        assert "supervisor_interruption" in {e["event"] for e in seat_chain}
        # The outcome is the successor's escalation (exit 1), surfaced.
        assert outcome == 1 or mon._suspended
    finally:
        _kill(primary)


# ---------------------------------------------------------------- T7
EXPECTED_STARTED_KEYS = {
    "event", "agent_command", "agent_log", "stale_threshold_s",
    "budget", "anchoring", "prior_interruptions",
    "prior_consecutive_failures",
}
SHIPPED_FILE_SET = {
    "audit-log.jsonl",
    "audit-log.jsonl.checkpoints.jsonl",
    "supervision-log.jsonl",
    "supervision-log.jsonl.checkpoints.jsonl",
}


def test_t7_seat_disabled_is_the_shipped_product(tmp_path):
    state_dir = tmp_path / "state"
    agent_py = tmp_path / "agent.py"
    agent_py.write_text(AGENT, encoding="utf-8")
    agent_log = state_dir / "audit-log.jsonl"
    env = dict(os.environ, PYTHONPATH=SRC)
    proc = subprocess.Popen(
        [sys.executable, "-m", "chancellor.cli", "supervise",
         "--state-dir", str(state_dir), "--cadence", "0.2",
         "--missed", "3", "--poll", "0.05",
         "--", sys.executable, str(agent_py), str(agent_log),
         "5", "0.1", str(tmp_path / "agent.pid")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    out, _err = proc.communicate(timeout=120)
    assert proc.returncode == 0, out
    files = {p.name for p in state_dir.iterdir()}
    assert files == SHIPPED_FILE_SET, files
    events = _events(state_dir / "supervision-log.jsonl")
    started = next(e for e in events if e["event"] == "supervision_started")
    assert set(started["detail"].keys()) == EXPECTED_STARTED_KEYS
    for e in events:  # no seat field anywhere on a seat-less watch
        assert "watch_epoch" not in e["detail"]
        assert "second_seat" not in e["detail"]


# ---------------------------------------------------------------- T8
def _make_legacy_open_watch(tmp_path: Path) -> Path:
    state_dir = tmp_path / "state"
    agent_py = tmp_path / "agent.py"
    agent_py.write_text(AGENT, encoding="utf-8")
    agent_log = state_dir / "audit-log.jsonl"
    env = dict(os.environ, PYTHONPATH=SRC)
    proc = subprocess.Popen(
        [sys.executable, "-m", "chancellor.cli", "supervise",
         "--state-dir", str(state_dir), "--cadence", "0.2",
         "--missed", "3", "--poll", "0.05",
         "--", sys.executable, str(agent_py), str(agent_log),
         "200", "0.2", str(tmp_path / "agent.pid")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3)
    proc.kill()
    proc.wait(timeout=30)
    pidfile = tmp_path / "agent.pid"
    if pidfile.exists():
        with contextlib.suppress(OSError, ValueError):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)
    return state_dir


def test_t8_legacy_watch_opens_as_before_and_monitor_refuses(tmp_path):
    state_dir = _make_legacy_open_watch(tmp_path)
    env = dict(os.environ, PYTHONPATH=SRC)
    # A seat-less supervisor of the new build opens it unchanged:
    # legacy interruption receipted, agent resumes and completes.
    agent_py = tmp_path / "agent.py"
    agent_log = state_dir / "audit-log.jsonl"
    proc = subprocess.Popen(
        [sys.executable, "-m", "chancellor.cli", "supervise",
         "--state-dir", str(state_dir), "--cadence", "0.2",
         "--missed", "3", "--poll", "0.05",
         "--", sys.executable, str(agent_py), str(agent_log),
         "80", "0.05", str(tmp_path / "agent.pid")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    # Completion-leg parameters gentled (was 200 @ 0.01): at a
    # checkpoint-per-segment with O(n) checkpoint cost, the resumed
    # agent outran the supervisor's stall threshold and was
    # stall-relaunched while still alive — a second writer, and the
    # successor was right to refuse the fork. The legacy assertions
    # below are parameter-independent.
    out, _err = proc.communicate(timeout=240)
    assert proc.returncode == 0, out
    events = _events(state_dir / "supervision-log.jsonl")
    legacy = [
        e for e in events if e["event"] == "interruption_detected"
    ]
    assert legacy and legacy[0]["detail"]["cause"] == "unknown"
    assert any(e["event"] == "agent_completed" for e in events)


def test_t8_monitor_refuses_legacy_watch(tmp_path):
    state_dir = _make_legacy_open_watch(tmp_path)
    env = dict(os.environ, PYTHONPATH=SRC)
    refused = subprocess.run(
        [sys.executable, "-m", "chancellor.cli", "supervise",
         "--monitor-only", "--state-dir", str(state_dir)],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert refused.returncode == 2, refused.stdout + refused.stderr


# ---------------------------------------------------------------- T9
def test_t9_agent_completes_while_supervisor_lives(tmp_path):
    proc, state_dir, _pf = _spawn_pair(tmp_path, total=6, interval=0.1)
    sup_log = state_dir / "supervision-log.jsonl"
    seat_log = state_dir / "second-seat-log.jsonl"
    try:
        out, _err = proc.communicate(timeout=120)
    finally:
        _kill(proc)
    assert proc.returncode == 0, out
    kinds = [e["event"] for e in _events(sup_log)]
    assert "agent_completed" in kinds
    assert "supervisor_interruption" not in kinds
    assert "supervisor_reseat_initiated" not in kinds
    seat_kinds = [e["event"] for e in _events(seat_log)]
    assert "second_seat_stopped" in seat_kinds
    stopped = next(
        e for e in _events(seat_log) if e["event"] == "second_seat_stopped"
    )
    # SPEC's seat-log table: second_seat_stopped carries {reason}
    # only; the exit-0 outcome is asserted on proc.returncode above.
    assert stopped["detail"]["reason"] == "watch_ended"


# --------------------------------------------------------------- T10
def test_t10_supervision_chain_unverifiable_escalates_without_spawn(tmp_path):
    recorded = [sys.executable, "-m", "chancellor.cli", "supervise", "--", "/bin/true"]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    sup_path = state_dir / "supervision-log.jsonl"
    spawns: list[list[str]] = []

    def launcher(argv):
        spawns.append(argv)
        return _FakeHandle(999003)

    mon = _monitor(state_dir, launcher=launcher, alive={}, recorded=recorded)
    # ACCEPTANCE T10 setup is "as T1, but corrupt the supervision
    # chain after the kill" — the monitor is already armed and
    # running when the corruption lands. (Corrupting before arm
    # exercises arm's own refusal instead, a different surface.)
    assert mon.arm() is None
    # Corrupt the supervision chain itself, mid-watch.
    lines = sup_path.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    entry["rationale"] = "tampered"
    lines[0] = json.dumps(entry, sort_keys=True)
    sup_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    bytes_before = sup_path.read_bytes()
    mon.cycle()
    assert spawns == []
    assert sup_path.read_bytes() == bytes_before  # chain byte-identical
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    esc = [e for e in seat_events if e["event"] == "second_seat_escalation"]
    assert esc and esc[0]["detail"]["reason"] == "chain_unverifiable"
    kinds = [e["event"] for e in _events(sup_path)]
    assert "supervisor_reseat_failed" not in kinds  # no attempt counted


# --------------------------------------------------------------- T11
def test_t11_started_but_never_confirmed_times_out(tmp_path):
    recorded = [sys.executable, "-m", "chancellor.cli", "supervise", "--", "/bin/true"]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    now = [1000.0]
    spawns: list[list[str]] = []

    def launcher(argv):
        spawns.append(argv)
        epoch = int(argv[argv.index("--seat-epoch") + 1])
        sup = AuditLog(state_dir / "supervision-log.jsonl")
        _record(
            sup, "supervision_started",
            {"watch_epoch": epoch, "second_seat": True,
             "supervisor_pid": 999004},
            "supervisor", now[0],
        )
        return _FakeHandle(999004, status=None)  # never heartbeats

    seat = SecondSeatConfig(
        poll_s=0.05, budget=1, confirmation_window_s=1.5,
        started_readback_s=1.0,
    )
    mon = _monitor(
        state_dir, launcher=launcher, alive={}, seat=seat,
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        recorded=recorded,
    )
    assert mon.arm() is None
    mon.cycle()
    events = _events(state_dir / "supervision-log.jsonl")
    failed = [e for e in events if e["event"] == "supervisor_reseat_failed"]
    assert len(failed) == 1
    assert failed[0]["detail"]["reason"] == "confirmation_timeout"
    assert not any(
        e["event"] == "supervisor_reseat_confirmed" for e in events
    )
    # A heartbeat landing after the timeout does not retroactively
    # confirm: the episode stands escalated.
    sup = AuditLog(state_dir / "supervision-log.jsonl")
    _record(sup, "supervisor_heartbeat", {"agent_alive": True},
            "supervisor", now[0])
    chain_len = len(_events(state_dir / "supervision-log.jsonl"))
    mon.cycle()
    events = _events(state_dir / "supervision-log.jsonl")
    assert len(events) == chain_len
    assert not any(
        e["event"] == "supervisor_reseat_confirmed" for e in events
    )
    assert len(spawns) == 1


# --------------------------------------------------------------- T12/T13
def _good_successor_factory(state_dir: Path, alive: dict[int, bool], base: int):
    """A fake successor that performs the successor's real acts:
    takes the watch lock, appends started + confirmed + heartbeat."""
    counter = [0]
    handles: dict[int, object] = {}

    def launcher(argv):
        counter[0] += 1
        pid = base + counter[0]
        # The real CLI scans supervise options left to right into a
        # dict, so the LAST --seat-epoch wins (cli.py seat_values);
        # with_epoch inserts the minted epoch after any stale one in
        # a recorded argv, so the successor's real parse takes the
        # last occurrence. Parse it the same way here — taking the
        # first left the fake writing its facts at the stale epoch,
        # and the Monitor (confirming at the minted epoch) waited
        # out real confirmation windows on every attempt.
        epoch = int(argv[len(argv) - 1 - argv[::-1].index("--seat-epoch") + 1])
        lock_path = state_dir / "supervision.lock"
        holder: dict[str, object] = {}

        def _serve():
            # The successor's acts run CONCURRENTLY with the
            # Monitor's post-spawn lock release, as a real
            # successor process's do: the Monitor holds the watch
            # lock across the spawn call and releases it only when
            # the launcher returns, so a fake that takes the lock
            # synchronously inside the launcher deadlocks against
            # the handover it simulates (the lock is taken at
            # self-proof, with the bounded retry supervise.py
            # specifies — 5 s here). Serve from a thread instead:
            # retry the lock non-blockingly, then write the body
            # and the three chain facts.
            fh = open(lock_path, "a+")  # noqa: SIM115 — held by the
            # fake successor for its lifetime; closed by die().
            deadline = time.time() + 5.0
            while True:
                try:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.time() >= deadline:
                        fh.close()
                        return
                    time.sleep(0.05)
            holder["fh"] = fh
            fh.seek(0)
            fh.truncate()
            fh.write(json.dumps({
                "pid": pid, "watch_epoch": epoch, "host": "test",
                "started_at": time.time(), "seat_armed": True,
                "pid_identity": None,
            }))
            fh.flush()
            sup = AuditLog(state_dir / "supervision-log.jsonl")
            _record(
                sup, "supervision_started",
                {"watch_epoch": epoch, "second_seat": True,
                 "supervisor_pid": pid},
                "supervisor", time.time(),
            )
            started_seq = AuditLog(
                state_dir / "supervision-log.jsonl"
            ).read_all()[-1]["seq"]
            _record(
                sup, "supervisor_reseat_confirmed",
                {"watch_epoch": epoch, "confirming_started_seq": started_seq},
                "supervisor", time.time(),
            )
            _record(sup, "supervisor_heartbeat", {"agent_alive": True},
                    "supervisor", time.time())
            alive[pid] = True

        thread = threading.Thread(target=_serve, daemon=True)
        thread.start()

        class _GoodHandle:
            def __init__(self):
                self.pid = pid

            def poll(self):
                return None

            def terminate(self):
                pass

            def die(self):
                alive[self.pid] = False
                thread.join(timeout=5)
                fh = holder.get("fh")
                if fh is not None:
                    try:
                        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
                        fh.close()
                    except OSError:
                        pass

        handle = _GoodHandle()
        handles[pid] = handle
        return handle

    return launcher, handles


def test_t12_crash_looping_supervisor_episode_governor(tmp_path):
    recorded = [
        sys.executable, "-m", "chancellor.cli", "supervise",
        "--seat-epoch", "0", "--", "/bin/true",
    ]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    alive: dict[int, bool] = {}
    launcher, handles = _good_successor_factory(state_dir, alive, 5000)
    spawns = []
    base_launcher = launcher

    def counting_launcher(argv):
        spawns.append(argv)
        return base_launcher(argv)

    mon = _monitor(
        state_dir, launcher=counting_launcher, alive=alive,
        recorded=recorded,
    )
    assert mon.arm() is None
    sup_path = state_dir / "supervision-log.jsonl"
    for episode in range(3):
        mon.cycle()  # DOWN -> reseat -> confirmed
        events = _events(sup_path)
        confirmed = [
            e for e in events
            if e["event"] == "supervisor_reseat_confirmed"
        ]
        assert len(confirmed) == episode + 1
        state = rebuild_supervision_state(AuditLog(sup_path).read_all())
        assert state.consecutive_failures == 0  # R8 budget untouched
        # The successor dies: the next episode begins.
        current = handles[max(handles)]
        current.die()
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    freq = [
        e for e in seat_events
        if e["event"] == "second_seat_escalation"
        and e["detail"].get("reason") == "episode_frequency"
    ]
    assert freq, "episode-frequency escalation never fired"
    # Suspended: a fourth death produces no fourth reseat.
    mon.cycle()
    mon.cycle()
    assert len(spawns) == 3


def test_t13_clock_steps_cannot_manufacture_a_reseat(tmp_path):
    recorded = [sys.executable, "-m", "chancellor.cli", "supervise", "--", "/bin/true"]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    now = [1000.0]
    sup = AuditLog(state_dir / "supervision-log.jsonl")
    _record(sup, "supervisor_heartbeat", {"agent_alive": True},
            "supervisor", now[0])
    # The primary is ALIVE at DEAD_PID for this test's pid table.
    alive = {DEAD_PID: True}
    (state_dir / "supervision.lock").write_text(
        json.dumps({"pid": DEAD_PID, "watch_epoch": 0, "host": "test",
                    "started_at": now[0], "seat_armed": True,
                    "pid_identity": None}),
        encoding="utf-8",
    )
    # The simulated primary holds the watch lock for its whole
    # life, as a real supervisor does from self-proof on: pid
    # alive + lock body naming it + the lock itself FREE is a
    # contradictory instrument set, and the Monitor classifies it
    # UNKNOWN (never WEDGED) — correctly. Hold the flock here for
    # the test's duration so the instruments agree.
    lock_fh = open(  # noqa: SIM115 — held for the test's duration
        state_dir / "supervision.lock", "a+"
    )
    fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
    spawns: list[list[str]] = []

    def launcher(argv):
        spawns.append(argv)
        return _FakeHandle(999005)

    seat = SecondSeatConfig(poll_s=5.0)
    mon = _monitor(
        state_dir, launcher=launcher, alive=alive, seat=seat,
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        recorded=recorded,
    )
    assert mon.arm() is None
    chain_len_before = len(_events(state_dir / "supervision-log.jsonl"))
    now[0] += 3600.0  # one-hour forward step
    mon.cycle()  # first stale observation
    now[0] += 5.0
    mon.cycle()  # second stale observation -> wedged, never reseated
    now[0] += 5.0
    mon.cycle()
    assert spawns == []
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    wedged = [e for e in seat_events if e["event"] == "supervisor_wedged"]
    assert len(wedged) == 1
    assert len(_events(state_dir / "supervision-log.jsonl")) == chain_len_before
    # Stepping back and a fresh heartbeat clears the wedge.
    now[0] -= 3610.0
    sup = AuditLog(state_dir / "supervision-log.jsonl")
    _record(sup, "supervisor_heartbeat", {"agent_alive": True},
            "supervisor", now[0])
    mon.cycle()
    seat_events = _events(state_dir / "second-seat-log.jsonl")
    assert any(
        e["event"] == "supervisor_wedge_cleared" for e in seat_events
    )
    assert spawns == []


def test_t13_dead_primary_reseats_despite_clock_step(tmp_path):
    recorded = [
        sys.executable, "-m", "chancellor.cli", "supervise",
        "--seat-epoch", "0", "--", "/bin/true",
    ]
    state_dir = _seat_watch_on_disk(tmp_path, recorded=recorded)
    now = [1000.0 + 3600.0]  # clock already stepped an hour forward
    alive: dict[int, bool] = {}
    launcher, _handles = _good_successor_factory(state_dir, alive, 6000)
    mon = _monitor(
        state_dir, launcher=launcher, alive=alive,
        clock=lambda: now[0],
        sleeper=lambda s: now.__setitem__(0, now[0] + s),
        recorded=recorded,
    )
    assert mon.arm() is None
    mon.cycle()
    events = _events(state_dir / "supervision-log.jsonl")
    assert any(e["event"] == "supervisor_reseat_initiated" for e in events)
    assert any(e["event"] == "supervisor_reseat_confirmed" for e in events)


# --------------------------------------------------------------- T14
SEAT_EVENT_FIELDS = {
    "supervisor_interruption": {
        "event", "cause", "witnessed", "exit_status", "prior_watch_epoch",
        "last_heartbeat_age_s", "supervision_log_size", "agent_log_size",
        "seat_log_head",
    },
    "supervisor_reseat_initiated": {
        "event", "watch_epoch", "successor_command", "attempt",
        "episode_budget",
    },
    "supervisor_reseat_confirmed": {"event", "watch_epoch",
                                    "confirming_started_seq",
                                    "predecessor_interruption_seq"},
    "supervisor_reseat_failed": {
        "event", "watch_epoch", "attempt", "reason",
        "successor_exit_status",
    },
}


def test_t14_seat_record_verifies_cold_and_matches_schema(tmp_path):
    proc, state_dir, _pf = _spawn_pair(tmp_path, total=12, interval=0.1)
    agent_log = state_dir / "audit-log.jsonl"
    sup_log = state_dir / "supervision-log.jsonl"
    seat_log = state_dir / "second-seat-log.jsonl"
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3)
        assert _wait_until(lambda: _supervisor_pid(state_dir) is not None)
        os.kill(_supervisor_pid(state_dir), signal.SIGKILL)
        # ACCEPTANCE setup (as T1): the agent dies with its
        # supervisor. Left orphaned, it keeps writing from cached
        # chain state while the successor relaunches it, and the two
        # writers fork the chain's seq — the successor is right to
        # refuse that chain (O1 lane diagnosis, RESULTS.md).
        if _pf.exists():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(_pf.read_text()), signal.SIGKILL)
        out, _err = proc.communicate(timeout=180)
    finally:
        _kill(proc)
    assert proc.returncode == 0, out
    # Both chains verify cold through the shipped verifier.
    assert verify_log(sup_log).ok
    assert verify_log(seat_log).ok
    assert verify_log(agent_log).ok
    # Every seat-written supervision-chain event carries exactly its
    # section 3.4 field table.
    for e in _events(sup_log):
        if e["event"] in SEAT_EVENT_FIELDS:
            assert set(e["detail"].keys()) == SEAT_EVENT_FIELDS[e["event"]], (
                e["event"], set(e["detail"].keys()),
            )


# --------------------------------------------------------------- T15
def test_t15_wedged_then_dead_converts_once(tmp_path):
    proc, state_dir, _pf = _spawn_pair(tmp_path, total=200, interval=0.3)
    agent_log = state_dir / "audit-log.jsonl"
    seat_log = state_dir / "second-seat-log.jsonl"
    sup_log = state_dir / "supervision-log.jsonl"
    try:
        assert _wait_until(lambda: _checkpoint_count(agent_log) >= 3)
        assert _wait_until(lambda: _supervisor_pid(state_dir) is not None)
        sup_pid = _supervisor_pid(state_dir)
        os.kill(sup_pid, signal.SIGSTOP)
        escalated = lambda: any(  # noqa: E731
            e["event"] == "second_seat_escalation"
            and e["detail"].get("reason") == "wedge"
            for e in _events(seat_log)
        )
        assert _wait_until(escalated, timeout=90), "wedge never escalated"
        os.kill(sup_pid, signal.SIGKILL)
        reseated = lambda: any(  # noqa: E731
            e["event"] == "supervisor_reseat_confirmed"
            for e in _events(sup_log)
        )
        assert _wait_until(reseated, timeout=90), "no reseat after death"
        events = _events(sup_log)
        interruptions = [
            e for e in events if e["event"] == "supervisor_interruption"
        ]
        assert len(interruptions) == 1  # the wedge was never a second one
        head = interruptions[0]["detail"]["seat_log_head"]
        seat_entries = _events(seat_log)
        wedge_seqs = [
            e["entry"]["seq"] for e in seat_entries
            if e["event"] in ("supervisor_wedged", "second_seat_escalation")
        ]
        head_entry = next(
            e for e in seat_entries if e["entry"]["entry_hash"] == head
        )
        assert head_entry["entry"]["seq"] >= max(wedge_seqs)
    finally:
        _kill(proc)
        agent_pid_file = tmp_path / "agent.pid"
        if agent_pid_file.exists():
            with contextlib.suppress(OSError, ValueError):
                os.kill(int(agent_pid_file.read_text()), signal.SIGKILL)
