"""Governor decision receipts — SPEC §5 (Chancellor, Governor of
Operations).

The Governor's receipt kinds ride the shipped receipts spine: entries
are appended through :class:`chancellor.escalation.AuditLog`, so they
carry the same hash chain, frame citation, signed checkpoints, and
offline verification (``chancellor.verify_log``) as every other
Chancellor receipt. Nothing here re-implements signing or chaining;
this module only names the Governor's kinds and shapes their bodies.

Kinds (§5.1): ``policy-verdict`` · ``routing`` · ``drift`` ·
``preload-issued`` · ``gate`` · ``pack-amendment``. The existing
``gate`` PASS/FAIL receipts keep their shipped semantics — the
Governor mints and reads them through this same surface.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from .escalation import AuditLog

RECEIPT_KINDS = (
    "policy-verdict",
    "routing",
    "drift",
    "preload-issued",
    "gate",
    "pack-amendment",
)

ENTRY_TYPE = "governor_receipt"


class GovernorReceipts:
    """A mint + query surface over an AuditLog for Governor entries."""

    def __init__(self, log: AuditLog | str | Path):
        self._log = log if isinstance(log, AuditLog) else AuditLog(log)

    @classmethod
    def open(cls, path: str | Path) -> GovernorReceipts:
        return cls(AuditLog(path))

    @property
    def log(self) -> AuditLog:
        return self._log

    def mint(self, kind: str, fields: dict[str, Any]) -> dict:
        """Append one Governor receipt of ``kind``; returns the stamped
        chain entry as written. Kind is validated against §5.1 — an
        unnamed kind is a new receipt class and does not slip in."""
        if kind not in RECEIPT_KINDS:
            raise ValueError(
                f"unknown governor receipt kind: {kind!r} "
                f"(kinds are fixed by SPEC §5.1: {', '.join(RECEIPT_KINDS)})"
            )
        body: dict[str, Any] = {
            "entry_type": ENTRY_TYPE,
            "kind": kind,
            "ts": time.time(),
            **fields,
        }
        return self._log.record_entry(body)

    def checkpoint(self) -> dict:
        """Sign an RFC 9162 (v2) checkpoint over the chain so far."""
        return self._log.checkpoint_v2()

    def entries(self, kind: str | None = None) -> list[dict]:
        return [
            entry
            for entry in self._log.read_all()
            if entry.get("entry_type") == ENTRY_TYPE
            and (kind is None or entry.get("kind") == kind)
        ]

    def query(
        self,
        *,
        rule: str | None = None,
        artifact: str | None = None,
        kind: str | None = None,
    ) -> list[dict]:
        """Receipt-chain slices for the failure -> diagnosis -> spec
        feed (§5.3): filter Governor entries by rule id, by artifact
        name, and/or by kind."""
        out = []
        for entry in self.entries():
            if kind is not None and entry.get("kind") != kind:
                continue
            if rule is not None and entry.get("rule") != rule:
                continue
            if artifact is not None and entry.get("artifact") != artifact:
                continue
            out.append(entry)
        return out
