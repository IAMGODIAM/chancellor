"""F-WABI-001 regression family (R0–R6 shape, as tests).

The hole: a pre-existing malformed agent log with zero parseable
entries and a missing checkpoint sidecar was adopted as a fresh
start (exit 0, unreceipted). The fix honors the initial verification
whenever a pre-existing agent log exists and is non-empty on disk.
Zero-byte decision (stated): a zero-byte log carries no committed
state and is treated exactly as no log — a fresh start.
"""

import sys
import time
from pathlib import Path

from chancellor.escalation import ActionClass, AuditLog, Decision, EscalationRequest
from chancellor.supervise import Supervisor, SupervisorConfig


class _Handle:
    def __init__(self, script):
        self._script = list(script)
        self.pid = 4242
        self.terminated = False

    def poll(self):
        return self._script.pop(0) if self._script else None

    def terminate(self):
        self.terminated = True


class _Launcher:
    def __init__(self, handles):
        self._handles = list(handles)
        self.calls = []

    def __call__(self, command):
        self.calls.append(command)
        return self._handles.pop(0)


def _run(tmp_path: Path, launcher: _Launcher) -> int:
    config = SupervisorConfig(
        agent_command=[sys.executable, "-c", "pass"],
        state_dir=tmp_path,
        cadence_s=1.0,
        missed=3,
        poll_s=0.01,
        heartbeat_s=10_000.0,
    )
    sup = Supervisor(
        config,
        launcher=launcher,
        snapshot_fn=lambda: None,
        emit=lambda _line: None,
    )
    return sup.run()


def _valid_log(path: Path, segments: int = 3) -> None:
    log = AuditLog(path)
    for i in range(segments):
        req = EscalationRequest(
            action="segment", action_class=ActionClass.COMPUTE, detail=f"s{i}"
        )
        log.record(Decision(req, True, "agent", "committed", time.time()))
        log.checkpoint()


def test_malformed_single_line_log_no_sidecar_halts(tmp_path):
    (tmp_path / "audit-log.jsonl").write_text("this is not json at all\n")
    launcher = _Launcher([_Handle([0])])
    assert _run(tmp_path, launcher) == 1
    assert launcher.calls == [], "agent must never launch onto unverified state"


def test_malformed_multiline_log_no_sidecar_halts(tmp_path):
    (tmp_path / "audit-log.jsonl").write_text("garbage\nmore garbage\n{broken\n")
    launcher = _Launcher([_Handle([0])])
    assert _run(tmp_path, launcher) == 1
    assert launcher.calls == []


def test_valid_log_missing_sidecar_halts(tmp_path):
    _valid_log(tmp_path / "audit-log.jsonl")
    sidecar = tmp_path / "audit-log.jsonl.checkpoints.jsonl"
    assert sidecar.exists()
    sidecar.unlink()
    launcher = _Launcher([_Handle([0])])
    assert _run(tmp_path, launcher) == 1
    assert launcher.calls == []


def test_zero_byte_log_is_a_fresh_start(tmp_path):
    (tmp_path / "audit-log.jsonl").write_bytes(b"")
    launcher = _Launcher([_Handle([0])])
    assert _run(tmp_path, launcher) == 0
    assert len(launcher.calls) == 1


def test_no_log_is_a_fresh_start(tmp_path):
    launcher = _Launcher([_Handle([0])])
    assert _run(tmp_path, launcher) == 0
    assert len(launcher.calls) == 1


def test_valid_log_with_sidecar_launches(tmp_path):
    _valid_log(tmp_path / "audit-log.jsonl")
    launcher = _Launcher([_Handle([0])])
    assert _run(tmp_path, launcher) == 0
    assert len(launcher.calls) == 1
