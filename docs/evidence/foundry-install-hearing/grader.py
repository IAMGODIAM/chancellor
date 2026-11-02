#!/usr/bin/env python3
"""The hearing grader of record for bundle B
(`local-install-hearing-probation`): a deterministic rubric function
implementing the bundle's filed rubric mechanically — six lines,
table order, exact format, true sums. No judgment in the loop.

Usage: python3 grader.py <artifact-path>
Prints one JSON line: {"verdict": "pass"|"fail", "lines_checked": n,
"errors": [...]}. This file is frozen on the hearing run card by
hash before L1; it is not tuned during the run."""
import json
import sys
from pathlib import Path

TABLE = [(7, 5), (12, 9), (23, 14), (8, 16), (31, 7), (19, 26)]


def grade_artifact(path: str) -> dict:
    lines = [
        ln for ln in Path(path).read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]
    errors: list[str] = []
    if len(lines) != len(TABLE):
        errors.append(f"expected {len(TABLE)} lines, found {len(lines)}")
    for i, (a, b) in enumerate(TABLE):
        if i >= len(lines):
            break
        want = f"{a} + {b} = {a + b}"
        if lines[i] != want:
            errors.append(f"line {i + 1}: {lines[i]!r} != {want!r}")
    return {
        "verdict": "fail" if errors else "pass",
        "lines_checked": len(lines),
        "errors": errors,
    }


if __name__ == "__main__":
    print(json.dumps(grade_artifact(sys.argv[1])))
