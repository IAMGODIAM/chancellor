"""The built-in second seat — Tier A watch recovery (SPEC, 2026-11-03).

The supervisor receipts an agent's death and stall; until now nothing
inside the product watched the supervisor. This module is the missing
live reader plus a bounded authority: a Monitor process that reads
the supervision chain, the watch lock, and OS process truth, and —
in exactly one classification, DOWN — starts a successor supervisor
through the product's ordinary verified paths.

The seat restores only the watch. It never approves or refuses on
merits, never touches the R8 resume budget, never alters config,
never writes agent state, and never repairs a chain (SPEC §4). Its
own acts are receipted: seat events on the supervision chain inside
the lock window, and its observations on its own seat log.

Designed invariants (SPEC §§1–6):
  * no clock reading can cause a reseat; only process truth can;
  * a wedged (alive-but-silent) primary is receipted and escalated,
    never reseated, never killed;
  * fencing is a watch lock (flock — the kernel releases it only at
    death) plus a monotone watch epoch minted on the chain, checked
    by fresh reads at the moment of the act, never from cache;
  * reseat attempts are budgeted (3 per episode), backed off, and
    confirmed from chain facts read back — never from the successor
    process merely existing.
"""

from __future__ import annotations

import fcntl
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from . import receipts
from .escalation import ActionClass, AuditLog, Decision, EscalationRequest
from .receipts import ChainIntegrityError
from .supervise import (
    ProcessHandle,
    SupervisorConfig,
    _default_launcher,
    pid_start_identity,
    read_lock_body,
    rebuild_supervision_state,
)
from .verify_log import verify_log

SEAT_DISCLOSURE = (
    "anchoring: Tier A — seat, supervisor, and agent share this "
    "machine and this session. Covered: supervisor-process death "
    "(reseat through verified paths), supervisor wedge (detection "
    "and escalation only). NOT covered: death of this machine, death "
    "of the session (seat and supervisor together), disk loss, a "
    "wedged supervisor's recovery. The seat's own silence is visible "
    "as seat-log heartbeat age."
)

# Classification vocabulary (SPEC §2.8 of the seat's loop contract).
ENDED = "ended"
DOWN = "down"
WEDGED = "wedged"
HEALTHY = "healthy"
UNKNOWN = "unknown"


@dataclass
class SecondSeatConfig:
    """The seat's bounded parameters (SPEC §5, §7.2). Values marked
    design values in the spec; every one is overridable by config so
    tests run thresholds in test time — the ratios are the contract."""

    budget: int = 3  # reseat attempts per episode
    poll_s: float = 30.0  # seat poll interval
    backoff_s: tuple[float, float] = (60.0, 240.0)  # after attempts 1, 2
    confirmation_window_s: float | None = None  # default: max(2×hb, 300)
    started_readback_s: float = 60.0  # started must be readable by then
    wedge_multiple: float = 2.0  # wedge at 2× heartbeat interval
    wedge_escalation_multiple: float = 3.0  # escalate at 3×
    episode_window_s: float = 3600.0  # rolling episode-frequency window
    episode_max: int = 3  # episodes per window before suspension

    def confirmation_window(self, heartbeat_interval_s: float) -> float:
        if self.confirmation_window_s is not None:
            return self.confirmation_window_s
        return max(2 * heartbeat_interval_s, 300.0)


def with_epoch(argv: list[str], epoch: int) -> list[str]:
    """Insert the seat-epoch option into a recorded supervise argv."""
    out = list(argv)
    flag = ["--seat-epoch", str(epoch)]
    if "--" in out:
        idx = out.index("--")
        return out[:idx] + flag + out[idx:]
    return out + flag


def _detail_of(entry: dict) -> dict:
    detail = entry.get("detail")
    if not isinstance(detail, str):
        return {}
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _events(entries: list[dict]) -> list[tuple[dict, dict]]:
    return [(e, _detail_of(e)) for e in entries]


@dataclass
class _Ground:
    entries: list[dict] = field(default_factory=list)
    chain_error: str | None = None
    state: object = None  # SupervisionState
    lock_body: dict | None = None
    lock_free: bool | None = None
    pid: int | None = None
    pid_alive: bool | None = None
    heartbeat_age_s: float | None = None
    terminal: str | None = None  # "agent_completed" | "escalation"


class Monitor:
    """The second seat for one watch. See the module docstring."""

    def __init__(
        self,
        config: SupervisorConfig,
        seat: SecondSeatConfig | None = None,
        *,
        supervisor_argv: list[str] | None = None,
        mode: str = "pair",  # "pair" (spawn the primary) | "attach"
        signer: receipts.Signer | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        supervisor_launcher: Callable[[list[str]], ProcessHandle] | None = None,
        pid_alive_fn: Callable[[int], bool] | None = None,
        pid_identity_fn: Callable[[int], str | None] | None = None,
        emit: Callable[[str], None] = print,
    ):
        self.config = config
        self.seat = seat if seat is not None else SecondSeatConfig()
        self.mode = mode
        self._signer = signer if signer is not None else receipts.default_signer()
        self._clock = clock
        self._sleeper = sleeper
        self._launcher = supervisor_launcher or _default_launcher
        self._pid_alive_fn = pid_alive_fn
        self._pid_identity_fn = pid_identity_fn or pid_start_identity
        self._emit = emit
        self.state_dir = Path(config.state_dir)
        self.supervision_log_path = self.state_dir / "supervision-log.jsonl"
        self.seat_log_path = self.state_dir / "second-seat-log.jsonl"
        self.watch_lock_path = self.state_dir / "supervision.lock"
        self.seat_lock_path = self.state_dir / "second-seat.lock"
        self._recorded_command = list(supervisor_argv) if supervisor_argv else None
        self._seat_log: AuditLog | None = None
        self._seat_lock_fh = None
        self._watch_lock_fh = None
        self._child: ProcessHandle | None = None  # current supervisor
        self._child_exit: int | None = None
        self._primary_pid: int | None = None
        self._anchored = False
        self._poll_count = 0
        self._stale_count = 0
        self._stale_since: float | None = None
        self._wedge_receipted = False
        self._wedge_escalated = False
        self._wedge_since: float | None = None
        self._unknown_active = False
        self._suspended = False
        self._suspend_after_seq: int = -1
        self._last_classification: str | None = None

    # ------------------------------------------------------------ OS
    def _pid_alive(self, pid: int, lock_body: dict | None) -> bool:
        if self._pid_alive_fn is not None:
            return self._pid_alive_fn(pid)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        except OSError:
            return False
        # Pid-reuse defeat: a recycled pid carries a different start
        # identity than the lock body recorded.
        recorded = (lock_body or {}).get("pid_identity")
        if recorded is not None:
            current = self._pid_identity_fn(pid)
            if current is not None and current != recorded:
                return False
        return True

    def _lock_free(self) -> bool | None:
        """Probe the watch lock without holding it: True = free."""
        if self._watch_lock_fh is not None:
            return False
        try:
            fh = self.watch_lock_path.open("a+", encoding="utf-8")
        except OSError:
            return None
        try:
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return False
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            return True
        finally:
            fh.close()

    def _acquire_watch_lock(self) -> bool:
        if self._watch_lock_fh is not None:
            return True
        try:
            fh = self.watch_lock_path.open("a+", encoding="utf-8")
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        self._watch_lock_fh = fh
        return True

    def _release_watch_lock(self) -> None:
        if self._watch_lock_fh is not None:
            try:
                self._watch_lock_fh.close()
            except OSError:
                pass
            self._watch_lock_fh = None

    # ------------------------------------------------------------ logs
    def _seat_receipt(self, action: str, *, event: str, detail: dict) -> None:
        assert self._seat_log is not None
        full = {"event": event, **detail}
        request = EscalationRequest(
            action=f"second-seat: {action}",
            action_class=ActionClass.COMPUTE,
            detail=json.dumps(full, sort_keys=True),
        )
        self._seat_log.record(
            Decision(request, True, "second-seat", action, self._clock())
        )
        self._seat_log.checkpoint()

    def _seat_head(self) -> str | None:
        if self._seat_log is None:
            return None
        entries = self._seat_log.read_all()
        return entries[-1].get("entry_hash") if entries else None

    def _chain_append(self, action: str, *, event: str, detail: dict) -> dict:
        """Append a seat event to the supervision chain. Caller holds
        the watch lock. Returns the written entry."""
        log = AuditLog(self.supervision_log_path, signer=self._signer)
        full = {"event": event, **detail}
        request = EscalationRequest(
            action=f"second-seat: {action}",
            action_class=ActionClass.COMPUTE,
            detail=json.dumps(full, sort_keys=True),
        )
        log.record(Decision(request, True, "second-seat", action, self._clock()))
        log.checkpoint()
        return log.read_all()[-1]

    # ------------------------------------------------------------ ground
    def _read_ground(self) -> _Ground:
        ground = _Ground()
        entries: list[dict] = []
        if self.supervision_log_path.exists():
            try:
                entries = AuditLog(
                    self.supervision_log_path, signer=self._signer
                ).read_all()
            except (ChainIntegrityError, OSError, ValueError) as exc:
                ground.chain_error = f"{type(exc).__name__}: {exc}"
                entries = []
                # Raw read for classification support (pid/terminal
                # facts are not trusted from a broken chain).
                try:
                    entries = [
                        json.loads(line)
                        for line in self.supervision_log_path.read_text(
                            encoding="utf-8"
                        ).splitlines()
                        if line.strip()
                    ]
                except (OSError, json.JSONDecodeError):
                    entries = []
        ground.entries = entries
        ground.state = rebuild_supervision_state(entries)
        ground.lock_body = read_lock_body(self.watch_lock_path)
        ground.lock_free = self._lock_free()
        # pid: the lock body names the watch's claimant; pair mode's
        # child is the same process at epoch 0 / after a reseat.
        pid = None
        if ground.lock_body is not None and isinstance(
            ground.lock_body.get("pid"), int
        ):
            pid = ground.lock_body["pid"]
        elif self._child is not None:
            pid = self._child.pid
        ground.pid = pid
        # Terminal receipt?
        for _entry, detail in reversed(_events(entries)):
            ev = detail.get("event")
            if ev in {"agent_completed", "escalation"}:
                ground.terminal = ev
                break
            if ev == "supervision_started":
                break
        # Heartbeat age from the newest supervisor_heartbeat ts.
        now = self._clock()
        for _entry, detail in reversed(_events(entries)):
            if detail.get("event") == "supervisor_heartbeat":
                ts = _entry.get("ts")
                if isinstance(ts, (int, float)):
                    ground.heartbeat_age_s = max(0.0, now - float(ts))
                break
        # Liveness.
        if pid is not None:
            if (
                self._child is not None
                and pid == self._child.pid
                and self.mode == "pair"
            ):
                if self._child_exit is None:
                    self._child_exit = self._child.poll()
                ground.pid_alive = self._child_exit is None
            else:
                ground.pid_alive = self._pid_alive(pid, ground.lock_body)
        return ground

    def _classify(self, ground: _Ground) -> str:
        state = ground.state
        # 1. ENDED — a terminal receipt exists and the watch is closed.
        if (
            ground.entries
            and not state.open_watch
            and ground.terminal is not None
            and ground.chain_error is None
        ):
            return ENDED
        pid, alive = ground.pid, ground.pid_alive
        # 2. DOWN — the primary's pid is proven gone.
        if pid is not None and alive is False:
            return DOWN
        if pid is not None and alive:
            # Cross-check: alive but the lock is free while the chain
            # advances — contradictory instruments; never act on them.
            started = any(
                d.get("event") == "supervision_started" for _e, d in _events(ground.entries)
            )
            if started and ground.lock_free:
                return UNKNOWN
            # 3. WEDGED — alive, heartbeat stale past 2× (two stale
            # observations at least one poll apart, SPEC §6.6).
            hb = self.config.heartbeat_interval_s
            age = ground.heartbeat_age_s
            if age is not None and age > self.seat.wedge_multiple * hb:
                now = self._clock()
                if self._stale_count >= 1 and self._stale_since is not None and (
                    now - self._stale_since >= self.seat.poll_s
                ):
                    return WEDGED
                return HEALTHY  # first stale observation; not yet a wedge
            return HEALTHY
        # No pid yet (pair launch window) — nothing to judge.
        return HEALTHY if self.mode == "pair" else UNKNOWN

    # ------------------------------------------------------------ arm
    def arm(self) -> str | None:
        """Take the seat lock, open the seat log, and (pair mode)
        spawn the primary. Returns a refusal string or None."""
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            fh = self.seat_lock_path.open("a+", encoding="utf-8")
            try:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                fh.close()
                return "second seat already armed for this watch (seat lock held)"
            self._seat_lock_fh = fh
        except OSError as exc:
            return f"second seat cannot arm: {exc}"
        try:
            self._seat_log = AuditLog(self.seat_log_path, signer=self._signer)
        except (ChainIntegrityError, OSError) as exc:
            return f"second seat cannot arm: seat log unverifiable: {exc}"
        ground = self._read_ground()
        if ground.chain_error is not None:
            return (
                "second seat cannot arm: supervision chain unverifiable: "
                f"{ground.chain_error}"
            )
        state = ground.state
        if self.mode == "attach":
            seat_started = any(
                d.get("event") == "supervision_started"
                and d.get("second_seat") is True
                and isinstance(d.get("watch_epoch"), int)
                for _e, d in _events(ground.entries)
            )
            if not seat_started:
                return (
                    "second seat cannot guard a legacy watch: no seat-enabled "
                    "supervision_started on the chain (no lock body, no pid "
                    "identity, no epoch to anchor to)"
                )
            if self._recorded_command is None:
                for entry in reversed(self._seat_log.read_all()):
                    detail = _detail_of(entry)
                    if detail.get("event") == "second_seat_armed" and isinstance(
                        detail.get("successor_command"), list
                    ):
                        self._recorded_command = detail["successor_command"]
                        break
            if self._recorded_command is None:
                return (
                    "second seat cannot arm in attach mode: no recorded "
                    "supervisor command (no prior second_seat_armed receipt)"
                )
            # Anchor the primary's identity for cause grading (§3.3).
            body = ground.lock_body or {}
            pid = body.get("pid")
            if isinstance(pid, int) and body.get("pid_identity") is not None:
                self._anchored = self._pid_identity_fn(pid) == body["pid_identity"]
            self._primary_pid = pid if isinstance(pid, int) else None
        else:  # pair
            if self._recorded_command is None:
                return "second seat cannot arm in pair mode without a command"
            self._seat_receipt(
                "second seat armed (pair)",
                event="second_seat_armed",
                detail={
                    "watch_epoch": state.watch_epoch,
                    "state_dir": str(self.state_dir),
                    "mode": "pair",
                    "anchoring": "tier_a_same_machine",
                    "successor_command": self._recorded_command,
                },
            )
            self._emit(f"[second-seat] {SEAT_DISCLOSURE}")
            argv = with_epoch(self._recorded_command, state.watch_epoch)
            try:
                self._child = self._launcher(argv)
            except OSError as exc:
                return f"second seat: primary spawn failed: {exc}"
            self._child_exit = None
            self._primary_pid = self._child.pid
            self._anchored = True
            return None
        # attach mode: receipt the adoption (§6.1 permits a later seat
        # adopting the watch; the adoption itself is receipted).
        self._seat_receipt(
            "second seat armed (attach)",
            event="second_seat_armed",
            detail={
                "watch_epoch": state.watch_epoch,
                "state_dir": str(self.state_dir),
                "mode": "attach",
                "anchoring": "tier_a_same_machine",
                "successor_command": self._recorded_command,
                "predecessor_seat_head": self._seat_head(),
            },
        )
        self._emit(f"[second-seat] {SEAT_DISCLOSURE}")
        return None

    # ------------------------------------------------------------ run
    def run(self, max_polls: int | None = None) -> int:
        refusal = self.arm()
        if refusal is not None:
            self._emit(f"[second-seat] REFUSED: {refusal}")
            self._emit(f"[second-seat] {SEAT_DISCLOSURE}")
            return 2
        while True:
            outcome = self.cycle()
            if outcome is not None:
                return outcome
            if max_polls is not None:
                max_polls -= 1
                if max_polls <= 0:
                    return -1  # still watching (test/instrumentation exit)
            self._sleeper(self.seat.poll_s)

    def cycle(self) -> int | None:
        """One poll: classify, and act in exactly one classification."""
        self._poll_count += 1
        ground = self._read_ground()
        cls = self._classify(ground)
        # Track stale observations for the two-observation wedge rule.
        hb = self.config.heartbeat_interval_s
        if (
            ground.heartbeat_age_s is not None
            and ground.heartbeat_age_s > self.seat.wedge_multiple * hb
            and ground.pid_alive
        ):
            if self._stale_count == 0:
                self._stale_since = self._clock()
            self._stale_count += 1
        else:
            self._stale_count = 0
            self._stale_since = None
        cls = self._classify(ground)  # re-classify with stale tracking
        self._last_classification = cls
        if self._poll_count % 10 == 0:
            self._seat_receipt(
                "second seat heartbeat",
                event="second_seat_heartbeat",
                detail={
                    "classification": cls,
                    "heartbeat_age_s": ground.heartbeat_age_s,
                },
            )
        if self._suspended:
            return self._cycle_suspended(ground)
        if cls == ENDED:
            self._seat_receipt(
                "second seat stopped — watch ended",
                event="second_seat_stopped",
                detail={"reason": "watch_ended"},
            )
            self._emit("[second-seat] watch ended; seat standing down.")
            return 0 if ground.terminal == "agent_completed" else 1
        if cls == DOWN:
            if ground.chain_error is not None:
                return self._on_chain_unverifiable(ground)
            return self._run_episode(ground)
        if cls == WEDGED:
            self._on_wedged(ground)
            return None
        if cls == HEALTHY:
            if self._wedge_receipted:
                duration = (
                    self._clock() - self._wedge_since
                    if self._wedge_since is not None
                    else None
                )
                self._seat_receipt(
                    "supervisor wedge cleared",
                    event="supervisor_wedge_cleared",
                    detail={"episode_duration_s": duration},
                )
                self._wedge_receipted = False
                self._wedge_escalated = False
                self._wedge_since = None
            self._unknown_active = False
            return None
        if cls == UNKNOWN:
            if not self._unknown_active:
                self._unknown_active = True
                self._seat_receipt(
                    "second seat: contradictory instruments",
                    event="second_seat_unknown",
                    detail={
                        "classification": UNKNOWN,
                        "heartbeat_age_s": ground.heartbeat_age_s,
                        "chain_error": ground.chain_error,
                    },
                )
            return None
        return None

    def _cycle_suspended(self, ground: _Ground) -> int | None:
        """After an escalation the seat keeps polling but never
        reseats (SPEC §5.3) until a human clears it: a fresh
        supervision_started from outside the seat."""
        if ground.terminal is not None and not ground.state.open_watch:
            self._seat_receipt(
                "second seat stopped — watch ended",
                event="second_seat_stopped",
                detail={"reason": "watch_ended"},
            )
            return 0 if ground.terminal == "agent_completed" else 1
        for entry, detail in _events(ground.entries):
            seq = entry.get("seq")
            if (
                detail.get("event") == "supervision_started"
                and isinstance(seq, int)
                and seq > self._suspend_after_seq
            ):
                self._suspended = False
                self._seat_receipt(
                    "second seat suspension cleared by an outside start",
                    event="second_seat_cleared",
                    detail={"by_started_seq": seq},
                )
                break
        return None

    # ------------------------------------------------------------ wedge
    def _on_wedged(self, ground: _Ground) -> None:
        age = ground.heartbeat_age_s
        if not self._wedge_receipted:
            self._wedge_receipted = True
            self._wedge_since = self._clock()
            self._seat_receipt(
                "supervisor wedged — alive, heartbeat stale",
                event="supervisor_wedged",
                detail={
                    "heartbeat_age_s": age,
                    "watch_epoch": ground.state.watch_epoch,
                    "pid": ground.pid,
                },
            )
            self._emit(
                "[second-seat] supervisor WEDGED (alive, heartbeat "
                f"age {age:.1f}s) — receipted; never reseated, never killed."
            )
        hb = self.config.heartbeat_interval_s
        if (
            not self._wedge_escalated
            and age is not None
            and age > self.seat.wedge_escalation_multiple * hb
        ):
            self._wedge_escalated = True
            self._seat_receipt(
                "second seat escalation: supervisor wedge persistent",
                event="second_seat_escalation",
                detail={
                    "reason": "wedge",
                    "episode": {
                        "heartbeat_age_s": age,
                        "watch_epoch": ground.state.watch_epoch,
                        "pid": ground.pid,
                    },
                    "attempts": 0,
                    "supervision_log_size": len(ground.entries),
                },
            )
            self._emit("[second-seat] ESCALATION: supervisor wedge persistent.")

    # ------------------------------------------------------------ chain broken
    def _on_chain_unverifiable(self, ground: _Ground) -> int | None:
        result = verify_log(self.supervision_log_path, signer=self._signer)
        self._seat_receipt(
            "second seat escalation: supervision chain unverifiable",
            event="second_seat_escalation",
            detail={
                "reason": "chain_unverifiable",
                "episode": {"failures": result.failures},
                "attempts": 0,
                "supervision_log_size": len(ground.entries),
            },
        )
        self._emit(
            "[second-seat] ESCALATION: supervision chain unverifiable — "
            "no append, no spawn, no repair."
        )
        self._suspended = True
        self._suspend_after_seq = max(
            (e.get("seq") for e in ground.entries if isinstance(e.get("seq"), int)),
            default=-1,
        )
        return None

    # ------------------------------------------------------------ episode
    def _episodes_in_window(self, entries: list[dict]) -> int:
        now = self._clock()
        count = 0
        for entry, detail in _events(entries):
            if detail.get("event") == "supervisor_interruption":
                ts = entry.get("ts")
                if isinstance(ts, (int, float)) and now - float(ts) <= (
                    self.seat.episode_window_s
                ):
                    count += 1
        return count

    def _escalate_seat(self, reason: str, episode: dict, attempts: int, entries: list[dict]) -> None:
        head = entries[-1].get("entry_hash") if entries else None
        self._seat_receipt(
            f"second seat escalation: {reason}",
            event="second_seat_escalation",
            detail={
                "reason": reason,
                "episode": episode,
                "attempts": attempts,
                "supervision_log_size": len(entries),
                "supervision_head": head,
                "seat_log_head": self._seat_head(),
            },
        )
        self._emit(f"[second-seat] ESCALATION: {reason}.")
        self._suspended = True
        self._suspend_after_seq = max(
            (e.get("seq") for e in entries if isinstance(e.get("seq"), int)),
            default=-1,
        )

    def _run_episode(self, ground: _Ground) -> int | None:
        """The reseat act (SPEC §3.2). Returns an exit code to stop,
        or None to keep watching."""
        # Episode-frequency governor, first half: a 4th episode inside
        # the window never opens (§6.7).
        if self._episodes_in_window(ground.entries) >= self.seat.episode_max:
            self._escalate_seat(
                "episode_frequency",
                {"watch_epoch": ground.state.watch_epoch},
                0,
                ground.entries,
            )
            return None
        # Step 1 — fresh reads; abort silently if DOWN no longer holds.
        fresh = self._read_ground()
        if self._classify(fresh) != DOWN:
            return None
        # Step 2 — verify the supervision chain read-only before any
        # append. A break ends self-repair for this watch (§6.3).
        result = verify_log(self.supervision_log_path, signer=self._signer)
        if not result.ok:
            return self._on_chain_unverifiable(fresh)
        # Step 3 — acquire the watch lock. A live holder means the
        # death classification was wrong or already handled.
        if not self._acquire_watch_lock():
            return None
        try:
            return self._episode_locked(fresh)
        finally:
            self._release_watch_lock()

    def _episode_locked(self, ground: _Ground) -> int | None:
        state = ground.state
        # Cause grading (§3.3): pair mode reaps the exit status
        # (proven); attach mode is proven only when the pid identity
        # was anchored at arm time, plausible otherwise.
        exit_status = self._child_exit if self.mode == "pair" else None
        witnessed = self.mode == "pair" and self._child is not None
        if exit_status is not None and witnessed:
            cause = "proven"
        elif self._anchored:
            cause = "proven"
        else:
            cause = "plausible"
        # Wedge conversion (T15): a wedged-then-dead episode receipts
        # exactly one interruption; its seat_log_head cross-references
        # the seat log holding the wedge record.
        try:
            interruption = self._chain_append(
                "supervisor interruption — primary dead",
                event="supervisor_interruption",
                detail={
                    "cause": cause,
                    "witnessed": witnessed,
                    "exit_status": exit_status,
                    "prior_watch_epoch": state.watch_epoch,
                    "last_heartbeat_age_s": ground.heartbeat_age_s,
                    "supervision_log_size": len(ground.entries),
                    "agent_log_size": state.last_agent_log_size,
                    "seat_log_head": self._seat_head(),
                },
            )
        except (ChainIntegrityError, OSError) as exc:
            # §6.8: an unrecorded reseat must not be spent from the
            # budget; receipt the failure in the seat log if writable.
            try:
                self._seat_receipt(
                    "second seat: chain append failed",
                    event="second_seat_append_failed",
                    detail={"error": f"{type(exc).__name__}: {exc}"},
                )
            except Exception:
                pass
            self._emit(f"[second-seat] chain append failed: {exc}")
            self._sleeper(self.seat.poll_s)
            return None
        interruption_seq = interruption.get("seq")
        self._wedge_receipted = False
        self._wedge_escalated = False
        self._wedge_since = None
        attempts = 0
        last_epoch = state.watch_epoch
        for attempt in range(1, self.seat.budget + 1):
            attempts = attempt
            # Re-verify before each attempt's append (§6.3 discipline).
            check = verify_log(self.supervision_log_path, signer=self._signer)
            if not check.ok:
                return self._on_chain_unverifiable(self._read_ground())
            epoch = self._read_ground().state.watch_epoch + 1
            last_epoch = epoch
            try:
                self._chain_append(
                    "supervisor reseat initiated",
                    event="supervisor_reseat_initiated",
                    detail={
                        "watch_epoch": epoch,
                        "successor_command": self._recorded_command,
                        "attempt": attempt,
                        "episode_budget": self.seat.budget,
                    },
                )
            except (ChainIntegrityError, OSError) as exc:
                self._emit(f"[second-seat] chain append failed: {exc}")
                self._sleeper(self.seat.poll_s)
                return None
            # Fresh tail re-read (F-WABI-010 law): the minted epoch
            # must still be the greatest and no terminal receipt may
            # have appeared since.
            tail = self._read_ground()
            if tail.terminal is not None and not tail.state.open_watch:
                return None  # the watch ended; ENDED handles it next poll
            argv = with_epoch(self._recorded_command or [], epoch)
            try:
                successor = self._launcher(argv)
            except OSError as exc:
                self._append_reseat_failed(
                    epoch, attempt, "spawn_error", None, str(exc)
                )
                outcome = self._after_failed_attempt(attempt)
                if outcome is not None:
                    return outcome
                continue
            # The handover: release the watch lock now that the
            # successor process exists; it takes the lock itself at
            # self-proof (with the epoch>0 retry, supervise.py).
            self._release_watch_lock()
            outcome, successor_live = self._confirm(successor, epoch)
            if outcome == "confirmed":
                self._child = successor
                self._child_exit = None
                self._primary_pid = successor.pid
                self._after_episode_close()
                return None
            if outcome == "confirmed_with_escalation":
                self._after_episode_close()
                return 1  # the restored watch escalated; a human holds it
            if outcome == "successor_refused":
                self._append_reseat_failed(epoch, attempt, "successor_refused", 2)
                entries = self._read_ground().entries
                self._escalate_seat(
                    "successor_refused",
                    {
                        "interruption_seq": interruption_seq,
                        "cause": cause,
                        "watch_epoch": epoch,
                    },
                    attempts,
                    entries,
                )
                return None
            # confirmation_timeout or successor died mid-window.
            reason = outcome
            code = successor.poll()
            self._append_reseat_failed(epoch, attempt, reason, code)
            outcome2 = self._after_failed_attempt(attempt)
            if outcome2 is not None:
                return outcome2
            # Re-acquire the watch lock for the next attempt's appends.
            if not self._acquire_watch_lock():
                return None
        # Budget exhausted.
        entries = self._read_ground().entries
        self._escalate_seat(
            "budget",
            {
                "interruption_seq": interruption_seq,
                "cause": cause,
                "watch_epoch": last_epoch,
            },
            attempts,
            entries,
        )
        return None

    def _after_failed_attempt(self, attempt: int) -> int | None:
        """Backoff between attempts (§5.1). Always returns None —
        named for symmetry with the episode close."""
        if attempt <= len(self.seat.backoff_s):
            self._sleeper(self.seat.backoff_s[attempt - 1])
        return None

    def _after_episode_close(self) -> None:
        """Episode-frequency governor, second half (§6.7): when the
        3rd episode inside the window closes, receipt the escalation
        and suspend — no 4th reseat until a human clears it."""
        entries = self._read_ground().entries
        if self._episodes_in_window(entries) >= self.seat.episode_max:
            self._escalate_seat(
                "episode_frequency",
                {"watch_epoch": self._read_ground().state.watch_epoch},
                0,
                entries,
            )

    def _append_reseat_failed(
        self,
        epoch: int,
        attempt: int,
        reason: str,
        exit_code: int | None,
        error: str | None = None,
    ) -> None:
        """Receipt a failed attempt on the chain inside a re-acquired
        lock window (§3.2 step 8). If a hung successor still holds
        the lock, the failure is receipted in the seat log instead —
        the attempt is counted either way, and the substitution is
        printed, never silent."""
        detail = {
            "watch_epoch": epoch,
            "attempt": attempt,
            "reason": reason,
            "successor_exit_code": exit_code,
        }
        if error:
            detail["error"] = error
        if self._acquire_watch_lock():
            try:
                self._chain_append(
                    "supervisor reseat failed",
                    event="supervisor_reseat_failed",
                    detail=detail,
                )
                return
            except (ChainIntegrityError, OSError):
                pass
            finally:
                self._release_watch_lock()
        self._seat_receipt(
            "supervisor reseat failed (seat-log record: watch lock held)",
            event="second_seat_attempt_failed",
            detail=detail,
        )
        self._emit(
            "[second-seat] reseat attempt failed; watch lock held by "
            "the successor — failure receipted in the seat log."
        )

    def _confirm(
        self, successor: ProcessHandle, epoch: int
    ) -> tuple[str, bool]:
        """Confirmation (§5.2): four chain facts read back, never the
        successor's mere existence. Returns (outcome, successor_live)
        with outcome in confirmed / confirmed_with_escalation /
        successor_refused / confirmation_timeout."""
        window = self.seat.confirmation_window(self.config.heartbeat_interval_s)
        deadline = self._clock() + window
        started_deadline = min(
            self._clock() + self.seat.started_readback_s, deadline
        )
        started_seq: int | None = None
        poll_step = min(self.seat.poll_s, 1.0)
        while True:
            status = successor.poll()
            if status == 2:
                return "successor_refused", False
            ground = self._read_ground()
            for entry, detail in _events(ground.entries):
                if (
                    detail.get("event") == "supervision_started"
                    and detail.get("watch_epoch") == epoch
                ):
                    seq = entry.get("seq")
                    started_seq = seq if isinstance(seq, int) else None
            if status == 1:
                # The restored watch did its job and escalated through
                # the gate — a confirmed reseat, not a failed one.
                if started_seq is not None:
                    return "confirmed_with_escalation", False
                return "confirmation_timeout", False
            if status == 0:
                if started_seq is not None:
                    return "confirmed", False
                return "confirmation_timeout", False
            if started_seq is not None:
                confirmed = any(
                    d.get("event") == "supervisor_reseat_confirmed"
                    and d.get("watch_epoch") == epoch
                    and d.get("confirming_started_seq") == started_seq
                    for _e, d in _events(ground.entries)
                )
                heartbeat = any(
                    d.get("event") == "supervisor_heartbeat"
                    and isinstance(e.get("seq"), int)
                    and started_seq is not None
                    and e["seq"] > started_seq
                    for e, d in _events(ground.entries)
                )
                lock_ok = (
                    ground.lock_body is not None
                    and ground.lock_body.get("pid") == successor.pid
                    and ground.lock_free is False
                )
                if confirmed and heartbeat and lock_ok:
                    return "confirmed", True
            now = self._clock()
            if started_seq is None and now >= started_deadline:
                return "confirmation_timeout", status is None
            if now >= deadline:
                return "confirmation_timeout", status is None
            self._sleeper(poll_step)
