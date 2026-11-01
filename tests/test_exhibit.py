"""Exhibit mode (chancellor.exhibit): the hearing, tested at CI pace.

The smoke test runs the full scenario fast with the gate auto-approved
and the tamper beat on: exit 0, drift 0, the clean chain verified, and
the altered copy rejected with the entry named. The determinism test
runs it twice and diffs the verdict blocks — the exhibit's printed
record must be a fixed target, like every other measured surface here.
"""

from __future__ import annotations

import re
from pathlib import Path

from chancellor.exhibit import run_exhibit, verdict_block


def _run(tmp_path: Path, name: str, **kwargs: object) -> tuple[int, str]:
    lines: list[str] = []
    rc = run_exhibit(
        state_dir=tmp_path / name,
        emit=lines.append,
        input_fn=lambda _prompt: "",
        **kwargs,  # type: ignore[arg-type]
    )
    return rc, "\n".join(lines)


def test_exhibit_fast_auto_tamper(tmp_path: Path) -> None:
    rc, out = _run(tmp_path, "a", fast=True, auto=True, tamper=True)
    assert rc == 0
    assert "the run has arrived at the gate" in out
    assert "payload_integrity" in out  # the fault beat's halt, named
    assert "drift: 0" in out
    assert "VERIFIED" in out
    assert re.search(r"tamper: entry seq \d+ altered after the fact", out)


def test_exhibit_determinism(tmp_path: Path) -> None:
    rc1, out1 = _run(tmp_path, "a", fast=True, auto=True)
    rc2, out2 = _run(tmp_path, "b", fast=True, auto=True)
    assert rc1 == rc2 == 0
    block = verdict_block(out1)
    assert block != ""
    assert block == verdict_block(out2)
