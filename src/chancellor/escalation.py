"""Escalation gates — where agents stop and humans decide.

Action classes are policy, declared in one place. Anything that spends
money, sends externally, publishes, acts irreversibly, or uses a
credential is a HUMAN gate. Everything else is auto-approved by policy.
A gate with no human attached DENIES by default: unattended authority
is not authority. Every decision — approve or deny, human or policy —
is written to an append-only audit log as a receipt.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

from . import receipts as _receipts


class ActionClass(StrEnum):
    READ = "read"
    DRAFT = "draft"
    COMPUTE = "compute"
    SPEND = "spend"
    EXTERNAL_SEND = "external_send"
    PUBLISH = "publish"
    IRREVERSIBLE = "irreversible"
    CREDENTIAL = "credential"


HUMAN_GATES: frozenset[ActionClass] = frozenset(
    {
        ActionClass.SPEND,
        ActionClass.EXTERNAL_SEND,
        ActionClass.PUBLISH,
        ActionClass.IRREVERSIBLE,
        ActionClass.CREDENTIAL,
    }
)


@dataclass
class EscalationRequest:
    action: str  # human-readable: what is being asked
    action_class: ActionClass
    detail: str = ""
    cost_usd: float | None = None
    node_id: str | None = None


@dataclass
class Decision:
    request: EscalationRequest
    approved: bool
    decider: str  # "policy" or the human's identifier
    rationale: str
    ts: float


# An approver takes a request and returns (approved, rationale).
Approver = Callable[[EscalationRequest], tuple[bool, str]]


class AuditLog:
    """Append-only JSONL receipt book. Existing lines are never rewritten.

    Every entry is hash-chained (see chancellor.receipts): it carries a
    sequence number, the previous entry's hash, its own entry hash, the
    receipt schema, and the action's AM-2 effect axes alongside the
    legacy action class. Opening an existing log re-verifies the chain
    and raises ChainIntegrityError on any break — a tampered log
    accepts no new receipts. Pre-chain legacy lines (plain JSONL from
    before the chain existed) are tolerated as a prefix: the first
    chained entry anchors to the last legacy line's hash, and the
    verifier reports the prefix as unchained.

    ``checkpoint()`` writes a signed Merkle checkpoint (issuer schema
    ``e5.receipt_checkpoint.v1``) to a sidecar file — the truncation
    defense a bare chain cannot provide. Verify a log offline with
    ``python -m chancellor.verify_log <log>``.
    """

    def __init__(
        self,
        path: str | Path,
        signer: _receipts.Signer | None = None,
        checkpoint_path: str | Path | None = None,
    ):
        self.path = Path(path)
        self.signer = signer if signer is not None else _receipts.default_signer()
        self.checkpoint_path = (
            Path(checkpoint_path)
            if checkpoint_path is not None
            else _receipts.default_checkpoint_path(self.path)
        )
        existing = self.read_all()
        # Rebuild (and verify) chain state from what is already on disk.
        self._state = _receipts.scan_chain(existing)

    def record(self, decision: Decision) -> None:
        state = self._state
        entry = {
            "schema": _receipts.SCHEMA,
            "seq": state.total_entries,
            "ts": decision.ts,
            "action": decision.request.action,
            "action_class": decision.request.action_class.value,
            "effect_axes": _receipts.effect_axes_for(
                decision.request.action_class.value
            ),
            "detail": decision.request.detail,
            "cost_usd": decision.request.cost_usd,
            "node_id": decision.request.node_id,
            "approved": decision.approved,
            "decider": decision.decider,
            "rationale": decision.rationale,
            "prev_hash": state.prev_hash,
        }
        entry["entry_hash"] = _receipts.entry_hash(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        state.total_entries += 1
        state.chained += 1
        state.leaves.append(entry["entry_hash"])
        state.prev_hash = entry["entry_hash"]

    # Chain-owned fields a caller-supplied body may never set itself.
    _RESERVED_FIELDS = frozenset({"schema", "seq", "prev_hash", "entry_hash"})

    def record_entry(self, fields: dict[str, Any]) -> dict:
        """Append a caller-shaped entry (e.g. a freeze_manifest or
        test_run body from chancellor.receipts) under the same chain
        discipline as record(): the log stamps schema/seq/prev_hash/
        entry_hash, and the entry is fsynced before state advances.
        Returns the stamped entry as written."""
        clash = self._RESERVED_FIELDS & fields.keys()
        if clash:
            raise ValueError(
                f"entry fields may not set chain-owned fields: {sorted(clash)}"
            )
        state = self._state
        entry: dict[str, Any] = {
            "schema": _receipts.SCHEMA,
            "seq": state.total_entries,
            **fields,
            "prev_hash": state.prev_hash,
        }
        entry["entry_hash"] = _receipts.entry_hash(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        state.total_entries += 1
        state.chained += 1
        state.leaves.append(entry["entry_hash"])
        state.prev_hash = entry["entry_hash"]
        return entry

    def checkpoint(self) -> dict:
        """Sign a Merkle checkpoint over every chained entry so far and
        append it to the checkpoint sidecar. Returns the envelope."""
        envelope = _receipts.build_checkpoint(
            signer=self.signer,
            log_size=self._state.chained,
            leaves=self._state.leaves,
            head_hash=self._state.prev_hash,
        )
        with self.checkpoint_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(envelope) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return envelope

    def checkpoint_v2(self) -> dict:
        """Sign an RFC 9162 (v2) checkpoint over every chained entry so
        far and append it to the checkpoint sidecar. Returns the
        envelope. The verifier accepts a v2 newest checkpoint under v2
        rules; v1 checkpoints in the same sidecar keep v1 rules."""
        envelope = _receipts.build_checkpoint_v2(
            signer=self.signer,
            log_size=self._state.chained,
            leaves=self._state.leaves,
            head_hash=self._state.prev_hash,
        )
        with self.checkpoint_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(envelope) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        return envelope

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [
            json.loads(line)
            for line in self.path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]


class AuditWriteError(RuntimeError):
    """A gate decision could not be written to the audit log.

    Record-or-halt (Council AM-10v): an approval that exists but is not
    recorded is authority exercised invisibly — worse than no decision.
    When this raises, the decision is NOT in effect; the caller must
    halt. The original write failure is chained as __cause__."""


class Gatekeeper:
    def __init__(
        self,
        audit_log: AuditLog | None = None,
        approver: Approver | None = None,
        human_id: str = "human",
    ):
        self.audit_log = audit_log
        self.approver = approver
        self.human_id = human_id

    def authorize(self, request: EscalationRequest) -> Decision:
        """Decide a gate request and receipt the decision.

        Fail-closed at the source (Council AM-10iii): an approver that
        raises has approved nothing — the exception becomes a DENY
        Decision, receipted like any other decision, instead of
        propagating as a bare crash the caller might mishandle. And a
        decision whose audit write fails raises AuditWriteError
        (record-or-halt, AM-10v): the approval is never left silently
        unrecorded.
        """
        try:
            decision = self._decide(request)
        except Exception as exc:
            decision = Decision(
                request,
                False,
                "policy",
                f"approver error — denied (fail-closed): {type(exc).__name__}: {exc}",
                time.time(),
            )
        if self.audit_log is not None:
            try:
                self.audit_log.record(decision)
            except Exception as exc:
                raise AuditWriteError(
                    f"audit write failed for gate decision on "
                    f"{request.action!r} — decision NOT in effect "
                    f"(record-or-halt): {type(exc).__name__}: {exc}"
                ) from exc
        return decision

    def _decide(self, request: EscalationRequest) -> Decision:
        if request.action_class not in HUMAN_GATES:
            return Decision(
                request,
                True,
                "policy",
                f"{request.action_class.value} is auto-approved by policy",
                time.time(),
            )
        if self.approver is None:
            # Fail-closed: no human attached -> the gate does not open.
            return Decision(
                request,
                False,
                "policy",
                "human gate with no approver attached — denied (fail-closed)",
                time.time(),
            )
        approved, rationale = self.approver(request)
        return Decision(request, bool(approved), self.human_id, rationale, time.time())
