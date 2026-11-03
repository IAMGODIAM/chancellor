"""Built-in supervision — the KEEP office (Tier A continuity).

Chancellor's other offices grade work, gate consequential acts, and
receipt decisions. None of them keeps an agent *going*: the harness
guarantees verifiable state survival and resume correctness, but
detection and relaunch used to live in hand-built scaffolding (cron
watchdogs, respawn scripts) that an end user does not have. This
module is that supervision, shipped in the product:

    chancellor supervise -- <the agent command>

The supervisor starts the agent as its child, watches the agent's
signed checkpoints, and on death verifies the receipt chain at the
newest signed checkpoint boundary before resuming anything. Every
death, verification, resume, and escalation is written as a signed
record in the supervisor's own audit log beside the agent's, in the
same governed format (chancellor.escalation.AuditLog), cross-
referencing the agent's chain head.

Honesty rules, carried from the soak record into product law:
  * a relaunch never proceeds on an unverified chain (R3);
  * an interruption's cause is graded proven / plausible / unknown
    from the evidence that survived — never fabricated (R6);
  * health is always stated with the checkpoint's age — a stale
    checkpoint is never reported as health (R1);
  * the supervisor prints what its anchoring cannot see (R11):
    Tier A shares the agent's machine, so machine death kills the
    watcher with the watched and nobody is left to notice.

Implemented against CONTINUITY-ANALYSIS §3 (R1–R11), Tier A scope.
Requirements map: R1 heartbeat-by-checkpoint (CheckpointSnapshot.age_s,
printed with every status), R2 dead-vs-stalled discrimination
(discriminate), R3 verify-before-resume (verify_at_checkpoint_boundary),
R4 supervised resume on the product's own checkpoint semantics, R5
provisional relaunch (confirmed only when the chain advances past the
loss point), R6 interruption receipts with graded causes, R7 drift at
resume is a gate event, R8 escalation budget (default 3), R9 supervisor
state derived from its own signed log, R10 launch-time self-proof with
named legs, R11 anchoring disclosure.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from . import receipts
from .escalation import (
    ActionClass,
    AuditLog,
    Decision,
    EscalationRequest,
    Gatekeeper,
)
from .installs import fold_all_probation, format_status_lines
from .receipts import ChainIntegrityError

# ------------------------------------------------------------------ causes
# R6: the kills/recoveries distinction as product law. A cause is
# PROVEN only when the supervisor witnessed the death and reaped the
# exit status; PLAUSIBLE when the process is confirmed gone but no exit
# status survived; UNKNOWN when no witness survived at all.
CAUSE_PROVEN = "proven"
CAUSE_PLAUSIBLE = "plausible"
CAUSE_UNKNOWN = "unknown"


def grade_cause(*, exit_status: int | None, witnessed: bool) -> str:
    """Grade an interruption's cause from the surviving evidence."""
    if witnessed and exit_status is not None:
        return CAUSE_PROVEN
    if witnessed or exit_status is not None:
        return CAUSE_PLAUSIBLE
    return CAUSE_UNKNOWN


# ------------------------------------------------------------- verdicts
class WatchVerdict(StrEnum):
    HEALTHY = "healthy"
    STALLED = "stalled"  # alive, checkpoint stale — anomaly, never relaunch
    DOWN = "down"  # dead — verify, then resume or escalate
    COMPLETED = "completed"  # exited 0 under its own power


def discriminate(
    *,
    process_alive: bool,
    exit_status: int | None,
    checkpoint_age_s: float,
    stale_threshold_s: float,
) -> WatchVerdict:
    """Dead vs stalled vs healthy, from process state + checkpoint age.

    A reaped exit status is death proven: DOWN immediately, with no
    staleness wait. Staleness discriminates the LIVE process: alive but
    older than the threshold is STALLED (congestion or a hung agent) —
    an anomaly to receipt, never a reason to start a second copy.
    """
    if exit_status is not None:
        return WatchVerdict.COMPLETED if exit_status == 0 else WatchVerdict.DOWN
    if not process_alive:
        return WatchVerdict.DOWN
    if checkpoint_age_s > stale_threshold_s:
        return WatchVerdict.STALLED
    return WatchVerdict.HEALTHY


# ------------------------------------------- boundary verification
@dataclass
class BoundaryVerification:
    """Verification of the agent's chain at its newest signed
    checkpoint boundary — the only state a resume may proceed from.
    Entries past the boundary are uncommitted by design (the product
    verifier's semantics) and are not judged here."""

    ok: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    log_size: int | None = None  # chained entries the checkpoint commits
    head_hash: str | None = None
    entries_present: int = 0  # chained entries currently in the log


def _parse_jsonl_lenient(path: Path) -> tuple[list[dict], bool]:
    """Parse a JSONL file, dropping a torn FINAL line (a kill landing
    mid-append leaves an uncommitted partial record — the T3 torn-
    record rule). Returns (rows, torn_tail_dropped). A malformed line
    anywhere else raises ValueError: that is corruption, not a tear."""
    rows: list[dict] = []
    lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    torn = False
    for pos, line in enumerate(lines):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            if pos == len(lines) - 1:
                torn = True
                break
            raise ValueError(f"malformed line {pos + 1} in {path}") from None
    return rows, torn


def verify_at_checkpoint_boundary(
    log_path: str | Path,
    checkpoint_path: str | Path | None = None,
    signer: receipts.Signer | None = None,
) -> BoundaryVerification:
    """Verify the chain at the newest signed checkpoint boundary:
    checkpoint signature, the committed prefix's hash chain, its Merkle
    root and head hash, and truncation (fewer chained entries present
    than the checkpoint commits). Fail-closed: no signed checkpoint
    means no verified boundary exists, and nothing may resume."""
    signer = signer if signer is not None else receipts.default_signer()
    log_path = Path(log_path)
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    failures: list[str] = []
    warnings: list[str] = []

    if not log_path.exists():
        return BoundaryVerification(
            ok=False, failures=[f"agent_log_not_found: {log_path}"]
        )
    try:
        rows, torn = _parse_jsonl_lenient(log_path)
    except ValueError as exc:
        return BoundaryVerification(ok=False, failures=[f"malformed_log: {exc}"])
    if torn:
        warnings.append("torn_tail_line_dropped: final partial line is uncommitted")
    entries_present = sum(1 for row in rows if "entry_hash" in row)

    if not cp_path.exists():
        return BoundaryVerification(
            ok=False,
            failures=[
                "no_signed_checkpoint: the log carries no signed "
                "checkpoint, so no verified boundary exists to resume "
                "from — the verifier refuses to guess"
            ],
            warnings=warnings,
            entries_present=entries_present,
        )
    try:
        envelopes, cp_torn = _parse_jsonl_lenient(cp_path)
    except ValueError as exc:
        return BoundaryVerification(
            ok=False,
            failures=[f"malformed_checkpoint_sidecar: {exc}"],
            warnings=warnings,
            entries_present=entries_present,
        )
    if cp_torn:
        warnings.append("torn_checkpoint_line_dropped: newest complete envelope used")
    if not envelopes:
        return BoundaryVerification(
            ok=False,
            failures=["no_signed_checkpoint: checkpoint sidecar is empty"],
            warnings=warnings,
            entries_present=entries_present,
        )
    newest = envelopes[-1]
    if not receipts.checkpoint_signature_valid(newest, signer):
        failures.append(
            "checkpoint_signature_invalid: newest checkpoint signature does not verify"
        )
    try:
        payload = receipts.checkpoint_payload(newest)
    except Exception:
        failures.append("checkpoint_malformed: newest envelope does not decode")
        return BoundaryVerification(
            ok=False,
            failures=failures,
            warnings=warnings,
            entries_present=entries_present,
        )
    if payload.get("schema") != receipts.CHECKPOINT_SCHEMA:
        failures.append(
            f"checkpoint_schema: {payload.get('schema')!r} != "
            f"{receipts.CHECKPOINT_SCHEMA!r}"
        )
    log_size = payload.get("log_size")
    if not isinstance(log_size, int) or log_size < 0:
        failures.append(f"checkpoint_log_size_invalid: {log_size!r}")
        return BoundaryVerification(
            ok=False,
            failures=failures,
            warnings=warnings,
            entries_present=entries_present,
        )
    if entries_present < log_size:
        failures.append(
            f"tail_truncation: checkpoint covers {log_size} chained "
            f"entries, log holds {entries_present}"
        )
        return BoundaryVerification(
            ok=False,
            failures=failures,
            warnings=warnings,
            log_size=log_size,
            entries_present=entries_present,
        )

    # Cut the committed prefix: rows up to and including the
    # log_size-th chained entry. Walk it with the chain scanner.
    prefix: list[dict] = []
    chained_seen = 0
    for row in rows:
        prefix.append(row)
        if "entry_hash" in row:
            chained_seen += 1
            if chained_seen == log_size:
                break
    try:
        state = receipts.scan_chain(prefix)
    except ChainIntegrityError as exc:
        failures.append(f"chain_broken: {exc}")
        return BoundaryVerification(
            ok=False,
            failures=failures,
            warnings=warnings,
            log_size=log_size,
            entries_present=entries_present,
        )
    if receipts.merkle_root(state.leaves) != payload.get("merkle_root"):
        failures.append(
            "checkpoint_root_mismatch: Merkle root over the committed "
            "prefix != checkpoint root"
        )
    if state.prev_hash != payload.get("head_receipt_hash"):
        failures.append("head_hash_mismatch: checkpoint head != committed prefix head")
    return BoundaryVerification(
        ok=not failures,
        failures=failures,
        warnings=warnings,
        log_size=log_size,
        head_hash=payload.get("head_receipt_hash"),
        entries_present=entries_present,
    )


# ------------------------------------------------- supervisor state
@dataclass
class SupervisionState:
    """The supervisor's own state, DERIVED from its signed supervision
    log on open — the log is the state, so a supervisor restart cannot
    lose an interruption or reset the R8 budget."""

    consecutive_failures: int = 0
    interruptions: int = 0
    escalations: int = 0
    open_watch: bool = False
    last_agent_log_size: int | None = None


def _detail_of(entry: dict) -> dict:
    detail = entry.get("detail")
    if not isinstance(detail, str):
        return {}
    try:
        parsed = json.loads(detail)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def rebuild_supervision_state(entries: list[dict]) -> SupervisionState:
    """Rebuild supervision state by replaying the supervision log's
    receipt details in order."""
    state = SupervisionState()
    for entry in entries:
        detail = _detail_of(entry)
        event = detail.get("event")
        if isinstance(detail.get("agent_log_size"), int):
            state.last_agent_log_size = detail["agent_log_size"]
        if isinstance(detail.get("entries_at_loss"), int):
            state.last_agent_log_size = detail["entries_at_loss"]
        if event == "supervision_started":
            state.open_watch = True
        elif event == "interruption_detected":
            state.interruptions += 1
        elif event == "resume_failed":
            state.consecutive_failures += 1
        elif event == "resume_confirmed":
            state.consecutive_failures = 0
        elif event == "escalation":
            state.escalations += 1
            state.open_watch = False
        elif event == "agent_completed":
            state.consecutive_failures = 0
            state.open_watch = False
    return state


# ------------------------------------------------------------- processes
class ProcessHandle(Protocol):
    """The supervisor's seam over a launched agent process."""

    @property
    def pid(self) -> int: ...

    def poll(self) -> int | None: ...

    def terminate(self) -> None: ...


class _PopenHandle:
    def __init__(self, proc: subprocess.Popen):
        self._proc = proc

    @property
    def pid(self) -> int:
        return self._proc.pid

    def poll(self) -> int | None:
        return self._proc.poll()

    def terminate(self) -> None:
        self._proc.terminate()


Launcher = Callable[[list[str]], ProcessHandle]


def _default_launcher(command: list[str]) -> ProcessHandle:
    return _PopenHandle(subprocess.Popen(command))


def _command_launchable(command: list[str]) -> bool:
    """Dry check of the launch path (R10's launch leg): the command
    exists and is executable. Never runs it."""
    if not command:
        return False
    argv0 = command[0]
    if os.sep in argv0 or (os.altsep and os.altsep in argv0):
        return Path(argv0).is_file() and os.access(argv0, os.X_OK)
    return shutil.which(argv0) is not None


# ------------------------------------------------------------- snapshots
@dataclass
class CheckpointSnapshot:
    """The agent's newest signed checkpoint, as read (reading is not
    trusting — verification is verify_at_checkpoint_boundary's job)."""

    log_size: int
    head_hash: str | None
    created_at: int | None
    age_s: float
    written_at: float | None = None  # sidecar write time, when known


# -------------------------------------------------------------- config
@dataclass
class SupervisorConfig:
    agent_command: list[str]
    state_dir: Path = Path(".chancellor")
    agent_log: Path | None = None  # default: <state_dir>/audit-log.jsonl
    cadence_s: float = 60.0  # the agent's expected checkpoint interval
    missed: int = 3  # stale after this many missed intervals (§5 default)
    budget: int = 3  # R8: consecutive failed resumes before escalation
    poll_s: float = 1.0
    heartbeat_s: float | None = None  # supervisor heartbeat (default: stale window)

    @property
    def stale_threshold_s(self) -> float:
        return self.cadence_s * self.missed

    @property
    def heartbeat_interval_s(self) -> float:
        if self.heartbeat_s is not None:
            return self.heartbeat_s
        return self.stale_threshold_s

    @property
    def agent_log_path(self) -> Path:
        if self.agent_log is not None:
            return self.agent_log
        return self.state_dir / "audit-log.jsonl"


ANCHORING_DISCLOSURE = (
    "anchoring: Tier A — supervisor and agent share this machine and "
    "this process tree. Covered: agent process death, stalls, chain "
    "verification before resume. NOT covered: death of this machine, "
    "death of the supervisor's own session/context, disk loss — if "
    "those happen, nobody is left to notice; the supervision log's "
    "heartbeat age is how silence becomes visible."
)


# ------------------------------------------------------------ supervisor
class Supervisor:
    """Tier A supervisor: launches the agent as its child, watches its
    signed checkpoints, verifies before every resume, receipts every
    interruption, and escalates to the human gate when the chain fails
    verification or the resume budget runs out.

    Exit codes from run(): 0 = the agent completed under supervision;
    1 = halted and escalated (human gate); 2 = launch-time refusal
    (self-proof failed — this supervisor cannot supervise here).
    """

    def __init__(
        self,
        config: SupervisorConfig,
        *,
        signer: receipts.Signer | None = None,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] = time.sleep,
        launcher: Launcher | None = None,
        approver=None,
        emit: Callable[[str], None] = print,
        snapshot_fn: Callable[[], CheckpointSnapshot | None] | None = None,
    ):
        self.config = config
        self._signer = signer if signer is not None else receipts.default_signer()
        self._clock = clock
        self._sleeper = sleeper
        self._launcher = launcher if launcher is not None else _default_launcher
        self._approver = approver
        self._emit = emit
        self._snapshot_fn = (
            snapshot_fn if snapshot_fn is not None else self._read_snapshot
        )
        self.state_dir = config.state_dir
        self.agent_log = config.agent_log_path
        self.agent_checkpoints = receipts.default_checkpoint_path(self.agent_log)
        self.supervision_log_path = self.state_dir / "supervision-log.jsonl"
        self._log: AuditLog | None = None
        self._state = SupervisionState()
        self._child: ProcessHandle | None = None
        self._agent_started_at = 0.0
        self._provisional_loss_size: int | None = None
        self._stall_open = False
        self._last_verified_size: int | None = None
        self._last_heartbeat = 0.0
        self._cadence_advisory_emitted = False
        self._cadence_checkpoint_seen = False
        self._cadence_checkpoint_key: (
            tuple[int, str | None, int | None, float | None] | None
        ) = None
        self._cadence_checkpoint_written_at: float | None = None
        self._cadence_fresh_start = False
        self._cadence_initial_launch = True

    # ------------------------------------------------------------ text
    def anchoring_disclosure(self) -> str:
        return ANCHORING_DISCLOSURE

    def _status(self, headline: str, age_s: float) -> None:
        """Every status carries the checkpoint's age (R1) — 'healthy'
        is earned per print, from fresh evidence."""
        snap_size = self._state.last_agent_log_size
        self._emit(
            f"[supervise] {headline} — agent checkpoint: "
            f"{snap_size if snap_size is not None else 'none yet'} "
            f"entries, age {age_s:.1f}s (stale threshold "
            f"{self.config.stale_threshold_s:.0f}s)"
        )
        self._emit_probation_status()

    def _emit_probation_status(self) -> None:
        """Probation surfaces (frame v2, spec §2 P6): when this
        watch's own chain carries capability-install records, the
        status line folds each capability's probation state from the
        chain and prints it age-stamped (fold head + its timestamp).
        Ordinary watches carry no such records and print nothing
        extra — the surface exists only where the state does."""
        if self._log is None:
            return
        entries = self._log.read_all()
        if not entries:
            return
        states = fold_all_probation(entries)
        if not states:
            return
        head = entries[-1].get("entry_hash")
        head_ts = entries[-1].get("ts")
        for line in format_status_lines(states, head=head):
            self._emit(f"[supervise] probation: {line} (head ts {head_ts})")

    # -------------------------------------------------- cadence advice
    def _snapshot_written_at(self, snap: CheckpointSnapshot, now: float) -> float:
        """Best available write time for a checkpoint snapshot."""
        if snap.written_at is not None:
            return snap.written_at
        if snap.created_at is not None and snap.created_at > 0:
            return float(snap.created_at)
        return now - snap.age_s

    def _emit_cadence_advisory(
        self,
        *,
        basis: str,
        observed_s: float,
        agent_log_size: int | None,
    ) -> None:
        """Receipt and print the once-per-watch cadence advisory.

        Advisory only: this method records a diagnosis and its remedy.
        It does not alter the stale threshold, gate a resume, escalate,
        or change dead-versus-stalled discrimination.
        """
        if self._cadence_advisory_emitted:
            return
        self._cadence_advisory_emitted = True
        threshold = self.config.stale_threshold_s
        remedy = (
            "set --cadence (SupervisorConfig.cadence_s) to the agent's "
            "signed-checkpoint interval"
        )
        if basis == "fresh_start_no_checkpoint":
            line = (
                "[supervise] CADENCE ADVISORY — no signed checkpoint after "
                f"{observed_s:.1f}s from a fresh start, reaching the stale "
                f"threshold {threshold:.1f}s (cadence "
                f"{self.config.cadence_s:.1f}s × missed {self.config.missed}). "
                f"Advisory only: {remedy}; no resume, escalation, or "
                "threshold changed."
            )
            observed_detail = {"observed_no_checkpoint_after_s": observed_s}
        else:
            line = (
                "[supervise] CADENCE ADVISORY — observed signed-checkpoint "
                f"interval {observed_s:.1f}s exceeds the stale threshold "
                f"{threshold:.1f}s (cadence {self.config.cadence_s:.1f}s "
                f"× missed {self.config.missed}). Advisory only: {remedy} "
                f"(about {observed_s:.0f}s); no resume, escalation, or "
                "threshold changed."
            )
            observed_detail = {"observed_checkpoint_interval_s": observed_s}
        self._receipt(
            "cadence advisory — checkpoint interval exceeds stale threshold",
            event="cadence_advisory",
            approved=True,
            rationale=(
                "The observed signed-checkpoint timing does not match "
                "the configured supervision cadence. Advisory only: no "
                "act was gated, no resume was blocked, and no escalation "
                "was raised."
            ),
            detail={
                "basis": basis,
                **observed_detail,
                "observed_s": observed_s,
                "cadence_s": self.config.cadence_s,
                "missed": self.config.missed,
                "stale_threshold_s": threshold,
                "agent_log_size": agent_log_size,
                "remedy": remedy,
                "advisory_only": True,
            },
        )
        assert self._log is not None
        self._log.checkpoint()
        self._emit(line)

    def _observe_cadence(self, snap: CheckpointSnapshot | None, now: float) -> None:
        """Look for the two pre-registered cadence-mismatch symptoms.

        (a) Two consecutive signed checkpoints are farther apart than
        the stale threshold; or (b) a watch that began with no signed
        checkpoint reaches the stale threshold still without one. The
        checkpoint baseline and advisory latch survive relaunches in
        the same supervisor run.
        """
        if self._cadence_advisory_emitted:
            return
        threshold = self.config.stale_threshold_s
        if snap is None:
            if self._cadence_fresh_start and not self._cadence_checkpoint_seen:
                observed_s = now - self._agent_started_at
                if observed_s >= threshold:
                    self._emit_cadence_advisory(
                        basis="fresh_start_no_checkpoint",
                        observed_s=observed_s,
                        agent_log_size=None,
                    )
            return

        self._cadence_checkpoint_seen = True
        written_at = self._snapshot_written_at(snap, now)
        key = (snap.log_size, snap.head_hash, snap.created_at, written_at)
        if key == self._cadence_checkpoint_key:
            return
        previous_written_at = self._cadence_checkpoint_written_at
        self._cadence_checkpoint_key = key
        self._cadence_checkpoint_written_at = written_at
        if previous_written_at is None:
            if self._cadence_fresh_start:
                first_wait_s = written_at - self._agent_started_at
                if first_wait_s >= threshold:
                    self._emit_cadence_advisory(
                        basis="fresh_start_no_checkpoint",
                        observed_s=first_wait_s,
                        agent_log_size=snap.log_size,
                    )
            return
        observed_s = written_at - previous_written_at
        if observed_s > threshold:
            self._emit_cadence_advisory(
                basis="consecutive_checkpoints",
                observed_s=observed_s,
                agent_log_size=snap.log_size,
            )

    # ---------------------------------------------------------- record
    def _receipt(
        self,
        action: str,
        *,
        event: str,
        approved: bool,
        rationale: str,
        detail: dict,
    ) -> None:
        assert self._log is not None
        full_detail = {"event": event, **detail}
        request = EscalationRequest(
            action=f"supervisor: {action}",
            action_class=ActionClass.COMPUTE,
            detail=json.dumps(full_detail, sort_keys=True),
        )
        self._log.record(
            Decision(request, approved, "supervisor", rationale, self._clock())
        )

    def _escalate(self, reason: str, detail: dict) -> Decision:
        """Escalation is a governed act with its own receipt, through
        the existing gate (Gatekeeper). It records the halt for the
        human; it never asks permission to force a resume (R3)."""
        assert self._log is not None
        gatekeeper = Gatekeeper(
            audit_log=self._log, approver=self._approver, human_id="supervisor-human"
        )
        request = EscalationRequest(
            action=f"supervisor escalation: {reason}",
            action_class=ActionClass.IRREVERSIBLE,
            detail=json.dumps({"event": "escalation", **detail}, sort_keys=True),
        )
        decision = gatekeeper.authorize(request)
        self._log.checkpoint()
        return decision

    # -------------------------------------------------------- snapshot
    def _read_snapshot(self) -> CheckpointSnapshot | None:
        """The agent's newest signed checkpoint (payload read, not
        trusted). Age is measured from the sidecar's last write — the
        instant the commit hit disk — since payload created_at is
        whole-second and would quantize sub-second cadences."""
        cp_path = self.agent_checkpoints
        if not cp_path.exists():
            return None
        try:
            envelopes, _torn = _parse_jsonl_lenient(cp_path)
        except (OSError, ValueError):
            return None
        if not envelopes:
            return None
        try:
            payload = receipts.checkpoint_payload(envelopes[-1])
        except Exception:
            return None
        log_size = payload.get("log_size")
        if not isinstance(log_size, int):
            return None
        try:
            written_at = cp_path.stat().st_mtime
        except OSError:
            return None
        created_at = payload.get("created_at")
        return CheckpointSnapshot(
            log_size=log_size,
            head_hash=payload.get("head_receipt_hash"),
            created_at=created_at if isinstance(created_at, int) else None,
            age_s=max(0.0, self._clock() - written_at),
            written_at=written_at,
        )

    # ------------------------------------------------------ self-proof
    def self_proof(self) -> str | None:
        """R10: before accepting a watch, prove the supervision
        channel works — observe, launch, persist. Any failure is a
        loud refusal naming the leg; a silent watch is never sold."""
        # Observe leg: the agent's state must be readable.
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            if self.agent_log.exists():
                self.agent_log.read_bytes()
            if self.agent_checkpoints.exists():
                self.agent_checkpoints.read_bytes()
        except OSError as exc:
            return (
                "observe leg failed: cannot read the agent's state "
                f"({self.agent_log}): {exc}"
            )
        # Launch leg: the agent command must be launchable (dry check).
        if not _command_launchable(self.config.agent_command):
            return (
                "launch leg failed: agent command is not executable: "
                f"{self.config.agent_command!r}"
            )
        # Persist leg: open the supervision log (its chain verifies at
        # open) and write + checkpoint the start receipt.
        try:
            self._log = AuditLog(self.supervision_log_path, signer=self._signer)
            self._state = rebuild_supervision_state(self._log.read_all())
            self._receipt(
                "supervision started",
                event="supervision_started",
                approved=True,
                rationale=(
                    "Supervisor accepted the watch; self-proof passed "
                    "(observe, launch, persist)."
                ),
                detail={
                    "agent_command": self.config.agent_command,
                    "agent_log": str(self.agent_log),
                    "stale_threshold_s": self.config.stale_threshold_s,
                    "budget": self.config.budget,
                    "anchoring": "tier_a_same_machine",
                    "prior_interruptions": self._state.interruptions,
                    "prior_consecutive_failures": self._state.consecutive_failures,
                },
            )
            self._log.checkpoint()
        except (ChainIntegrityError, OSError) as exc:
            return (
                "persist leg failed: the supervision log cannot be "
                f"opened or written ({self.supervision_log_path}): {exc}"
            )
        return None

    # ----------------------------------------------------------- launch
    def _launch(self) -> None:
        if self._cadence_initial_launch:
            # The fresh-start advisory case is defined by the state of
            # the watch when this run first launches its agent: no
            # signed checkpoint existed to inherit. Relaunches in the
            # same run deliberately do not reset the advisory latch or
            # this classification.
            self._cadence_fresh_start = not self.agent_checkpoints.exists()
            self._cadence_initial_launch = False
        self._child = self._launcher(self.config.agent_command)
        self._agent_started_at = self._clock()
        self._stall_open = False

    # -------------------------------------------------------------- run
    def run(self) -> int:
        # The cadence advisory is latched per Supervisor.run() — one
        # advisory in this watch, including across agent relaunches.
        # A later supervisor run is a new watch and may advise again;
        # the latch is not rebuilt from a prior run's supervision log.
        self._cadence_advisory_emitted = False
        self._cadence_checkpoint_seen = False
        self._cadence_checkpoint_key = None
        self._cadence_checkpoint_written_at = None
        self._cadence_fresh_start = False
        self._cadence_initial_launch = True
        refusal = self.self_proof()
        if refusal is not None:
            self._emit(f"[supervise] REFUSED: {refusal}")
            self._emit(f"[supervise] {self.anchoring_disclosure()}")
            return 2
        self._emit(f"[supervise] {self.anchoring_disclosure()}")
        self._last_heartbeat = self._clock()

        # A previous watch left open (the supervisor itself died
        # mid-watch) is an interruption with no surviving witness:
        # receipt it at its honest grade before anything else (R6).
        if self._state.open_watch:
            self._receipt(
                "interruption discovered at supervisor restart",
                event="interruption_detected",
                approved=True,
                rationale=(
                    "The previous supervision ended without a terminal "
                    "receipt; no witness survived, so the cause is "
                    "graded unknown and the record does not guess."
                ),
                detail={
                    "cause": CAUSE_UNKNOWN,
                    "witnessed": False,
                    "agent_log_size": self._state.last_agent_log_size,
                },
            )
            self._state.interruptions += 1

        # A first launch onto existing state is a resume: no resume
        # proceeds on an unverified chain (R3). F-WABI-001: the
        # verification's failure is honored whenever a pre-existing
        # agent log exists and is non-empty ON DISK — file presence +
        # size, not parseability. A malformed log with zero parseable
        # entries is still existing state; adopting it as a fresh
        # start would launch onto an unverified chain. A zero-byte
        # log carries no entries and no committed state, so it is
        # treated exactly as no log: a fresh start (a checkpoint
        # sidecar committing entries against it still triggers the
        # honored path via log_size, and fails as truncation).
        if self.agent_log.exists():
            initial = verify_at_checkpoint_boundary(
                self.agent_log, self.agent_checkpoints, self._signer
            )
            try:
                pre_existing_nonempty = self.agent_log.stat().st_size > 0
            except OSError:
                pre_existing_nonempty = False
            if pre_existing_nonempty or initial.log_size:
                if not initial.ok:
                    self._receipt(
                        "chain verification failed before first launch",
                        event="chain_verification",
                        approved=False,
                        rationale=(
                            "The agent's existing chain does not verify "
                            "at its signed checkpoint boundary; the "
                            "supervisor refuses to launch onto it."
                        ),
                        detail={"failures": initial.failures},
                    )
                    self._escalate(
                        "existing agent chain failed verification",
                        {"failures": initial.failures},
                    )
                    self._status("HALTED — escalated to the human gate", 0.0)
                    return 1
                self._last_verified_size = initial.log_size

        try:
            self._launch()
        except OSError as exc:
            self._receipt(
                "initial launch failed",
                event="resume_failed",
                approved=False,
                rationale=(
                    "The agent command passed self-proof but could not "
                    f"be launched: {exc}. The halt is escalated."
                ),
                detail={"launch_error": str(exc)},
            )
            self._escalate("initial launch failed", {"launch_error": str(exc)})
            self._status("HALTED — launch failed, escalated", 0.0)
            return 1
        while True:
            outcome = self._poll_once()
            if outcome is not None:
                return outcome
            self._sleeper(self.config.poll_s)

    # ------------------------------------------------------------- poll
    def _poll_once(self) -> int | None:
        assert self._child is not None  # invariant: run() launches first
        status = self._child.poll()
        snap = self._snapshot_fn()
        now = self._clock()
        if snap is not None:
            self._state.last_agent_log_size = snap.log_size
            age = snap.age_s
        else:
            age = now - self._agent_started_at
        self._observe_cadence(snap, now)

        if status is not None:
            if status == 0:
                self._receipt(
                    "agent completed",
                    event="agent_completed",
                    approved=True,
                    rationale="The agent exited cleanly under supervision.",
                    detail={
                        "exit_status": 0,
                        "agent_log_size": snap.log_size if snap else None,
                    },
                )
                assert self._log is not None
                self._log.checkpoint()
                self._status("agent completed", age)
                return 0
            return self._on_death(exit_status=status, witnessed=True, snap=snap)

        verdict = discriminate(
            process_alive=True,
            exit_status=None,
            checkpoint_age_s=age,
            stale_threshold_s=self.config.stale_threshold_s,
        )
        if verdict is WatchVerdict.STALLED:
            if not self._stall_open:
                self._stall_open = True
                self._receipt(
                    "agent stalled — checkpoint stale, process alive",
                    event="stall_anomaly",
                    approved=False,
                    rationale=(
                        "The agent process lives but its checkpoint is "
                        "past the stale threshold: congestion or a hang, "
                        "not a death. No second copy is started (R2)."
                    ),
                    detail={
                        "checkpoint_age_s": age,
                        "agent_log_size": snap.log_size if snap else None,
                    },
                )
                self._status("STALLED — anomaly receipted, not relaunched", age)
        else:
            self._stall_open = False

        # R5: a relaunch is provisional until the chain advances past
        # the loss point while the agent lives.
        if (
            self._provisional_loss_size is not None
            and snap is not None
            and snap.log_size > self._provisional_loss_size
        ):
            self._provisional_loss_size = None
            self._state.consecutive_failures = 0
            self._receipt(
                "resume confirmed — chain advancing past the loss point",
                event="resume_confirmed",
                approved=True,
                rationale=(
                    "The resumed agent is alive and its checkpoint has "
                    "advanced past the loss point; the relaunch has "
                    "outlived its launcher (R5)."
                ),
                detail={"agent_log_size": snap.log_size},
            )

        # R7: when the committed boundary moves, re-verify it; drift or
        # corruption at resume is a gate event, not a retry.
        if (
            snap is not None
            and snap.log_size > 0
            and snap.log_size != self._last_verified_size
        ):
            check = verify_at_checkpoint_boundary(
                self.agent_log, self.agent_checkpoints, self._signer
            )
            self._last_verified_size = snap.log_size
            if not check.ok:
                self._child.terminate()
                self._receipt(
                    "drift detected — boundary moved and no longer verifies",
                    event="drift_detected",
                    approved=False,
                    rationale=(
                        "A new checkpoint boundary fails verification "
                        "while the agent lives: the agent is halted and "
                        "the finding escalated, never retried (R7)."
                    ),
                    detail={"failures": check.failures},
                )
                self._escalate(
                    "chain drift detected under a live agent",
                    {"failures": check.failures},
                )
                self._status("HALTED — drift escalated to the human gate", age)
                return 1

        # R9/Tier A floor: signed supervisor heartbeat, so silence
        # itself is detectable by anything that can read a file's age.
        if now - self._last_heartbeat >= self.config.heartbeat_interval_s:
            self._last_heartbeat = now
            self._receipt(
                "supervisor heartbeat",
                event="supervisor_heartbeat",
                approved=True,
                rationale="Supervisor alive; agent state as recorded.",
                detail={
                    "agent_log_size": snap.log_size if snap else None,
                    "agent_checkpoint_age_s": age,
                    "consecutive_failures": self._state.consecutive_failures,
                },
            )
            assert self._log is not None
            self._log.checkpoint()
        return None

    # ------------------------------------------------------------- death
    def _on_death(
        self,
        *,
        exit_status: int | None,
        witnessed: bool,
        snap: CheckpointSnapshot | None,
    ) -> int | None:
        """A confirmed death: classify the cause honestly, verify the
        chain, and resume — or halt and escalate. Returns an exit code
        to stop, or None to keep watching the resumed agent."""
        assert self._log is not None
        now = self._clock()
        entries_at_loss = snap.log_size if snap is not None else 0
        age = snap.age_s if snap is not None else now - self._agent_started_at
        cause = grade_cause(exit_status=exit_status, witnessed=witnessed)

        # Was this death a failed resume (R5/R8 accounting)?
        if self._provisional_loss_size is not None:
            if entries_at_loss > self._provisional_loss_size:
                # The chain advanced past the loss point before this
                # death: the resume had confirmed by effect.
                self._state.consecutive_failures = 0
                self._receipt(
                    "resume confirmed — chain advanced before a later death",
                    event="resume_confirmed",
                    approved=True,
                    rationale=(
                        "The resumed agent advanced its checkpoint past "
                        "the loss point before dying again; the earlier "
                        "resume counts as confirmed, not failed."
                    ),
                    detail={"agent_log_size": entries_at_loss},
                )
            else:
                self._state.consecutive_failures += 1
                self._receipt(
                    "resume failed — agent died before advancing",
                    event="resume_failed",
                    approved=False,
                    rationale=(
                        "The relaunched agent died inside its "
                        "provisional window, before its checkpoint "
                        "advanced past the loss point — a distinct "
                        "event, not a silent retry (R5)."
                    ),
                    detail={
                        "consecutive_failures": self._state.consecutive_failures,
                        "budget": self.config.budget,
                        "entries_at_loss": entries_at_loss,
                    },
                )
            self._provisional_loss_size = None

        self._state.interruptions += 1
        self._receipt(
            "interruption detected — agent down",
            event="interruption_detected",
            approved=True,
            rationale=(
                f"Interruption {self._state.interruptions}: the agent "
                f"stopped at {entries_at_loss} committed entries "
                f"(checkpoint age {age:.1f}s at detection). Cause: "
                f"{cause} — graded from the evidence that survived."
            ),
            detail={
                "cause": cause,
                "witnessed": witnessed,
                "exit_status": exit_status,
                "entries_at_loss": entries_at_loss,
                "checkpoint_age_s": age,
                "agent_head_hash": snap.head_hash if snap else None,
            },
        )
        self._status(
            f"interruption {self._state.interruptions} detected (cause: {cause})",
            age,
        )

        if self._state.consecutive_failures >= self.config.budget:
            self._receipt(
                "resume budget exhausted",
                event="budget_exhausted",
                approved=False,
                rationale=(
                    f"{self._state.consecutive_failures} consecutive "
                    f"resumes failed (budget {self.config.budget}); the "
                    "supervisor stops and escalates rather than "
                    "looping (R8)."
                ),
                detail={
                    "consecutive_failures": self._state.consecutive_failures,
                    "budget": self.config.budget,
                },
            )
            self._escalate(
                "resume budget exhausted",
                {
                    "consecutive_failures": self._state.consecutive_failures,
                    "entries_at_loss": entries_at_loss,
                },
            )
            self._status("HALTED — budget exhausted, escalated", age)
            return 1

        # R3: verify before resume, always.
        check = verify_at_checkpoint_boundary(
            self.agent_log, self.agent_checkpoints, self._signer
        )
        self._receipt(
            "chain verified at checkpoint boundary"
            if check.ok
            else "chain verification FAILED",
            event="chain_verification",
            approved=check.ok,
            rationale=(
                "The chain verifies at the newest signed checkpoint "
                "boundary; resume may proceed from that boundary."
                if check.ok
                else "The chain does not verify; resume is refused — "
                "never forced, never repaired by guessing (R3)."
            ),
            detail={
                "ok": check.ok,
                "failures": check.failures,
                "warnings": check.warnings,
                "boundary_log_size": check.log_size,
                "entries_present": check.entries_present,
            },
        )
        if not check.ok:
            self._escalate(
                "chain verification failed — resume refused",
                {"failures": check.failures, "entries_at_loss": entries_at_loss},
            )
            self._status("HALTED — verification failed, escalated", age)
            return 1
        self._last_verified_size = check.log_size

        # R4: resume on the product's own semantics — relaunch the
        # agent; it rebuilds from its last completed checkpoint. A
        # launch that cannot even start is a failed resume (R8's own
        # scenario: the executable is gone) and consumes budget like
        # any other, bounded by the budget check below.
        while True:
            try:
                self._launch()
                break
            except OSError as exc:
                self._state.consecutive_failures += 1
                self._receipt(
                    "resume failed — agent could not be launched",
                    event="resume_failed",
                    approved=False,
                    rationale=(
                        f"The relaunch itself failed: {exc}. A launch "
                        "failure consumes resume budget like any other "
                        "failed resume (R8)."
                    ),
                    detail={
                        "launch_error": str(exc),
                        "consecutive_failures": self._state.consecutive_failures,
                        "budget": self.config.budget,
                    },
                )
                if self._state.consecutive_failures >= self.config.budget:
                    self._escalate(
                        "resume budget exhausted",
                        {
                            "consecutive_failures": self._state.consecutive_failures,
                            "entries_at_loss": entries_at_loss,
                        },
                    )
                    self._status("HALTED — budget exhausted, escalated", age)
                    return 1
                self._sleeper(self.config.poll_s)
        self._provisional_loss_size = check.log_size
        self._receipt(
            "agent resumed from verified boundary",
            event="resume_launched",
            approved=True,
            rationale=(
                f"Agent relaunched from the verified boundary at "
                f"{check.log_size} entries; the relaunch is "
                "provisional until the chain advances (R5)."
            ),
            detail={
                "boundary_log_size": check.log_size,
                "consecutive_failures": self._state.consecutive_failures,
            },
        )
        self._status("agent resumed (provisional)", age)
        return None
