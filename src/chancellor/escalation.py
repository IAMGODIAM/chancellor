"""Escalation gates — where agents stop and humans decide.

Action classes are policy, declared in one place. Anything that spends
money, sends externally, publishes, acts irreversibly, or uses a
credential is a HUMAN gate. Everything else is auto-approved by policy.
A gate with no human attached DENIES by default: unattended authority
is not authority. Every decision — approve or deny, human or policy —
is written to an append-only audit log as a receipt. A refusal is a
first-class receipted outcome, not an absence: every denial carries a
named refusal state (see REFUSAL_STATES), and every receipt names the
governing frame it was decided under (chancellor.receipts, FRAME).
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
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
    # Internal classes, never a valid worker declaration: NONE marks a
    # receipt for a node that took no action; UNCLASSIFIED marks a request
    # the policy could not classify (always denied).
    NONE = "none"
    UNCLASSIFIED = "unclassified"
    # The ninth class (frame v2, clause 6): an agent gaining a new
    # capability is a gated act — proposed, checked, decided,
    # receipted, verified live, reversible. Governed end to end by
    # chancellor.installs.
    CAPABILITY_INSTALL = "capability_install"


HUMAN_GATES: frozenset[ActionClass] = frozenset(
    {
        ActionClass.SPEND,
        ActionClass.EXTERNAL_SEND,
        ActionClass.PUBLISH,
        ActionClass.IRREVERSIBLE,
        ActionClass.CREDENTIAL,
        ActionClass.CAPABILITY_INSTALL,
    }
)


# --------------------------------------------------------------- refusals
# Receipts-on-refusal (Council M10, ADAPT — pattern after LaSalle/CAPPZ
# KeyZ Gate): a refusal is not an absence, it is a record with a reason.
# Every refusal this gate issues is receipted carrying one of these
# named states, issuable by the gate alone, without the refused party's
# cooperation. The vocabulary is Chancellor's own, enumerated from this
# gate and the approved specs (benefits-realization memo §M10). The
# states this gate can reach today are wired where they occur; the cap
# states await the cap object's build (its spec is Button 4's),
# frame-mismatch is the verifier's named failure, and
# verification-failed is the supervisor's R3 state — its receipts carry
# the frame through AuditLog, and stamping that state is the
# supervisor lane's follow-up.
REFUSAL_NO_APPROVER = "no-approver-attached"
REFUSAL_APPROVER_DECLINED = "approver-declined"
REFUSAL_APPROVER_ERROR = "approver-error"
REFUSAL_CAP_MODE_OFF = "cap-mode-off"
REFUSAL_CAP_WINDOW_EXCEEDED = "cap-window-exceeded"
REFUSAL_CAP_CEILING_EXCEEDED = "cap-ceiling-exceeded"
REFUSAL_CAP_COMMAND_UNAVAILABLE = "cap-command-unavailable"
REFUSAL_FRAME_MISMATCH = "frame-mismatch"
REFUSAL_VERIFICATION_FAILED = "verification-failed"
REFUSAL_UNCLASSIFIED = "unclassified-action"
REFUSAL_NODE_FAILED = "node-failed"
REFUSAL_RECONCILE_MISMATCH = "reconcile-mismatch"
REFUSAL_DECLARATION_MISMATCH = "declaration-mismatch"
REFUSAL_INERT_VIOLATION = "inert-violation"
REFUSAL_BROKERED_DENIAL = "brokered-call-denied"
REFUSAL_UNBROKERED_EFFECT = "unbrokered-effect"

# The install register (frame v2, clause 6): the Foundry manager's
# pre-flight states, the scope check, and the budget fold, mapped
# once, here, to Chancellor-side names (the mapping table is the
# contract — chancellor.installs records refusals under these states
# and names the Foundry state verbatim in the rationale). Wired in
# chancellor.installs, where the arc runs.
REFUSAL_INSTALL_INCOMPATIBLE = "install-incompatible"
REFUSAL_INSTALL_UNLICENSED = "install-unlicensed"
REFUSAL_INSTALL_PIN_MISMATCH = "install-pin-mismatch"
REFUSAL_INSTALL_PAYLOAD_ESCAPE = "install-payload-escape"
REFUSAL_INSTALL_UNCONSENTED_BUILD = "install-unconsented-build"
REFUSAL_INSTALL_SNAPSHOT_FAILED = "install-snapshot-failed"
REFUSAL_INSTALL_OUT_OF_SCOPE = "install-out-of-scope"
REFUSAL_INSTALL_COST_REFUSED = "install-cost-refused"
REFUSAL_INSTALL_BUDGET_EXHAUSTED = "install-budget-exhausted"

REFUSAL_STATES: frozenset[str] = frozenset(
    {
        REFUSAL_NO_APPROVER,
        REFUSAL_APPROVER_DECLINED,
        REFUSAL_APPROVER_ERROR,
        REFUSAL_CAP_MODE_OFF,
        REFUSAL_CAP_WINDOW_EXCEEDED,
        REFUSAL_CAP_CEILING_EXCEEDED,
        REFUSAL_CAP_COMMAND_UNAVAILABLE,
        REFUSAL_FRAME_MISMATCH,
        REFUSAL_VERIFICATION_FAILED,
        REFUSAL_UNCLASSIFIED,
        REFUSAL_NODE_FAILED,
        REFUSAL_RECONCILE_MISMATCH,
        REFUSAL_DECLARATION_MISMATCH,
        REFUSAL_INERT_VIOLATION,
        REFUSAL_BROKERED_DENIAL,
        REFUSAL_UNBROKERED_EFFECT,
        REFUSAL_INSTALL_INCOMPATIBLE,
        REFUSAL_INSTALL_UNLICENSED,
        REFUSAL_INSTALL_PIN_MISMATCH,
        REFUSAL_INSTALL_PAYLOAD_ESCAPE,
        REFUSAL_INSTALL_UNCONSENTED_BUILD,
        REFUSAL_INSTALL_SNAPSHOT_FAILED,
        REFUSAL_INSTALL_OUT_OF_SCOPE,
        REFUSAL_INSTALL_COST_REFUSED,
        REFUSAL_INSTALL_BUDGET_EXHAUSTED,
    }
)


@dataclass
class EscalationRequest:
    action: str  # human-readable: what is being asked
    # The class the requester declares. It can only make the decided class
    # stricter than the policy table's, never looser (see ActionPolicy).
    action_class: ActionClass | str | None = None
    detail: str = ""
    cost_usd: float | None = None
    node_id: str | None = None
    # Policy keys: the tool being invoked and/or the effects it has.
    tool: str | None = None
    effects: tuple[str, ...] = ()
    # Digest of the arguments the act runs with (interception layer).
    args_sha256: str | None = None
    # The class as declared by the requester, kept for the receipt once
    # the gate has replaced action_class with the decided class.
    declared_class: str | None = None
    # Set by the broker on a brokered call: binds this decision to the
    # outcome record written after the call runs.
    call_id: str | None = None
    # The capability this request belongs to, when it does (frame v2:
    # a probationary capability's gated uses, and the install arc's
    # own requests). Trailing + defaulted; AuditLog.record() stamps it
    # into the entry ONLY when set — requests of the existing classes
    # never set it, so their receipts stay byte-identical.
    capability_id: str | None = None
    # AM-2 request-side seam: axes the REQUEST carries beyond the
    # action class's static floor (e.g. computed by the install
    # governor from a bundle's declared permissions). AuditLog.record
    # unions it over the floor when present. Request-side only —
    # never part of the entry body beyond the recorded union. The
    # existing classes never set it; their receipts are unchanged.
    effect_axes: tuple[str, ...] | None = None


@dataclass
class Decision:
    request: EscalationRequest
    approved: bool
    decider: str  # "policy" or the human's identifier
    rationale: str
    ts: float
    # Named refusal state (REFUSAL_STATES) when this decision is a
    # refusal; None on approvals. Trailing + defaulted: existing
    # positional constructions (the supervisor's) are unaffected.
    refusal_state: str | None = None


# An approver takes a request and returns (approved, rationale).
Approver = Callable[[EscalationRequest], tuple[bool, str]]


# ----------------------------------------------------------------- policy
# The action class is decided by this table, not by the worker. The table
# is keyed by tool name and by effect axis; a requester's self-declared
# class can only tighten the result. Anything the table cannot classify is
# denied (fail-closed).
_STRICTNESS: Mapping[ActionClass, int] = MappingProxyType(
    {
        ActionClass.NONE: 0,
        ActionClass.READ: 1,
        ActionClass.DRAFT: 2,
        ActionClass.COMPUTE: 3,
        ActionClass.EXTERNAL_SEND: 10,
        ActionClass.PUBLISH: 11,
        ActionClass.SPEND: 12,
        ActionClass.CREDENTIAL: 13,
        ActionClass.IRREVERSIBLE: 14,
        ActionClass.CAPABILITY_INSTALL: 15,
    }
)


def strictest(classes: list[ActionClass]) -> ActionClass:
    """The strictest of the given classes (any human gate outranks every
    auto-approved class)."""
    return max(classes, key=lambda c: _STRICTNESS[c])


DEFAULT_TOOL_POLICY: Mapping[str, ActionClass] = MappingProxyType(
    {
        "read_file": ActionClass.READ,
        "web_search": ActionClass.READ,
        "fetch": ActionClass.READ,
        "draft_text": ActionClass.DRAFT,
        "compute": ActionClass.COMPUTE,
        "send_email": ActionClass.EXTERNAL_SEND,
        "send_message": ActionClass.EXTERNAL_SEND,
        "post_webhook": ActionClass.EXTERNAL_SEND,
        "make_payment": ActionClass.SPEND,
        "wire_transfer": ActionClass.SPEND,
        "purchase": ActionClass.SPEND,
        "publish_post": ActionClass.PUBLISH,
        "deploy_release": ActionClass.PUBLISH,
        "delete_file": ActionClass.IRREVERSIBLE,
        "drop_table": ActionClass.IRREVERSIBLE,
        "merge_change": ActionClass.IRREVERSIBLE,
        "use_credential": ActionClass.CREDENTIAL,
        "read_secret": ActionClass.CREDENTIAL,
    }
)

DEFAULT_EFFECT_POLICY: Mapping[str, ActionClass] = MappingProxyType(
    {
        "money_movement": ActionClass.SPEND,
        "external_visibility": ActionClass.EXTERNAL_SEND,
        "irreversibility": ActionClass.IRREVERSIBLE,
        "credential_exposure": ActionClass.CREDENTIAL,
    }
)


def coerce_class(value: object) -> ActionClass | None:
    """A declared class as an ActionClass, or None when it is not one.
    Strings are matched case- and whitespace-insensitively (model output
    drifts); the internal classes are never a valid declaration."""
    cls: ActionClass | None = None
    if isinstance(value, ActionClass):
        cls = value
    elif isinstance(value, str):
        try:
            cls = ActionClass(value.strip().lower())
        except ValueError:
            return None
    if cls is ActionClass.UNCLASSIFIED:
        return None
    return cls


@dataclass(frozen=True)
class Classification:
    """The policy's verdict on a request: the decided class, or a denial
    reason when the request cannot be classified."""

    action_class: ActionClass
    denied_reason: str | None = None


@dataclass(frozen=True)
class ActionPolicy:
    """The policy table. Tables passed in are copied into read-only
    mappings at construction, so nothing that holds the original (or this
    policy) can change a class afterwards."""

    tools: Mapping[str, ActionClass] = field(
        default_factory=lambda: DEFAULT_TOOL_POLICY
    )
    effects: Mapping[str, ActionClass] = field(
        default_factory=lambda: DEFAULT_EFFECT_POLICY
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "tools", MappingProxyType(dict(self.tools)))
        object.__setattr__(self, "effects", MappingProxyType(dict(self.effects)))

    def tool_class(self, tool: object) -> ActionClass | None:
        """The table's class for a tool name, or None when the table does
        not know it."""
        if not isinstance(tool, str):
            return None
        return self.tools.get(tool.strip().lower())

    @staticmethod
    def _deny(reason: str) -> Classification:
        return Classification(ActionClass.UNCLASSIFIED, reason)

    # CC 14 (radon) — one branch per way a request can fail to classify.
    def classify(self, request: EscalationRequest) -> Classification:
        declared: ActionClass | None = None
        if request.action_class is not None:
            declared = coerce_class(request.action_class)
            if declared is None:
                return self._deny(
                    f"unknown action class {request.action_class!r} — denied "
                    "(fail-closed)"
                )
        floors: list[ActionClass] = []
        if request.tool is not None:
            if not isinstance(request.tool, str):
                return self._deny("malformed tool — denied (fail-closed)")
            tool_class = self.tools.get(request.tool.strip().lower())
            if tool_class is None:
                return self._deny(
                    f"tool {request.tool!r} is not in the policy table — denied "
                    "(fail-closed)"
                )
            floors.append(tool_class)
        effects = request.effects
        if isinstance(effects, str):
            effects = (effects,)
        if not isinstance(effects, (tuple, list)):
            return self._deny("malformed effects — denied (fail-closed)")
        for effect in effects:
            effect_class = (
                self.effects.get(effect.strip().lower())
                if isinstance(effect, str)
                else None
            )
            if effect_class is None:
                return self._deny(
                    f"effect {effect!r} is not in the policy table — denied "
                    "(fail-closed)"
                )
            floors.append(effect_class)
        if not floors:
            # No policy basis. A declaration can add a human gate, but an
            # auto-approved class with nothing behind it is not accepted.
            if declared is None:
                return self._deny("no classification — denied (fail-closed)")
            if declared not in HUMAN_GATES:
                return self._deny(
                    "declared class has no policy basis (no tool or effect) — "
                    "denied (fail-closed)"
                )
            return Classification(declared)
        decided = strictest(floors + ([declared] if declared is not None else []))
        return Classification(decided)


DEFAULT_POLICY = ActionPolicy()


def _class_value(value: object) -> str:
    return (
        value.value
        if isinstance(value, ActionClass)
        else ActionClass.UNCLASSIFIED.value
    )


# Checkpoints seal automatically after this many chained entries unless the
# log is built with another interval (None disables auto-sealing).
DEFAULT_CHECKPOINT_EVERY = 16


class AuditLog:
    """Append-only JSONL receipt book. Existing lines are never rewritten.

    Every entry is hash-chained (see chancellor.receipts): it carries a
    sequence number, the previous entry's hash, its own entry hash, the
    receipt schema, and the action's AM-2 effect axes alongside the
    legacy action class. Entries written since the frame's adoption
    carry receipt schema v2: the governing frame's identifier and hash
    inside the committed body, and — on verdict records — a
    ``refusal_state`` naming why a refusal was issued (null on
    approvals, so both sides of every decision are countable).
    Opening an existing log re-verifies the chain
    and raises ChainIntegrityError on any break — a tampered log
    accepts no new receipts. Pre-chain legacy lines (plain JSONL from
    before the chain existed) are tolerated as a prefix: the first
    chained entry anchors to the last legacy line's hash, and the
    verifier reports the prefix as unchained.

    The log seals itself: after every ``checkpoint_every`` chained entries
    (default ``DEFAULT_CHECKPOINT_EVERY``) it writes a checkpoint without
    being asked, so the unsealed tail is bounded. Pass ``None`` to leave
    sealing entirely to the caller.

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
        checkpoint_every: int | None = DEFAULT_CHECKPOINT_EVERY,
    ):
        if checkpoint_every is not None and checkpoint_every < 1:
            raise ValueError("checkpoint_every must be a positive integer or None")
        self.checkpoint_every = checkpoint_every
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
        # AM-2 seam: axes are the class's static floor, unioned with
        # any request-side axes the caller computed (install governor:
        # from the bundle's declared permissions). Requests that do
        # not set the field get the floor alone — unchanged bytes.
        effect_axes = _receipts.effect_axes_for(
            _class_value(decision.request.action_class)
        )
        if decision.request.effect_axes is not None:
            effect_axes = sorted(set(effect_axes) | set(decision.request.effect_axes))
        entry: dict[str, Any] = {
            "schema": _receipts.SCHEMA,
            **_receipts.current_frame_fields(),
            "seq": state.total_entries,
            "ts": decision.ts,
            "action": decision.request.action,
            "action_class": _class_value(decision.request.action_class),
            "effect_axes": effect_axes,
            "detail": decision.request.detail,
            "cost_usd": decision.request.cost_usd,
            "node_id": decision.request.node_id,
            "approved": decision.approved,
            "refusal_state": decision.refusal_state,
            "decider": decision.decider,
            "rationale": decision.rationale,
            "prev_hash": state.prev_hash,
        }
        request = decision.request
        if (
            request.tool is not None
            or request.effects
            or request.declared_class is not None
            or request.args_sha256 is not None
            or request.call_id is not None
        ):
            entry.update(
                {
                    "tool": request.tool,
                    "effects": list(request.effects),
                    "declared_class": request.declared_class,
                    "args_sha256": request.args_sha256,
                    "call_id": request.call_id,
                }
            )
        if decision.request.capability_id is not None:
            entry["capability_id"] = decision.request.capability_id
        entry["entry_hash"] = _receipts.entry_hash(entry)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        state.total_entries += 1
        state.chained += 1
        state.leaves.append(entry["entry_hash"])
        state.prev_hash = entry["entry_hash"]
        self._maybe_seal()

    def _maybe_seal(self) -> None:
        """Seal a checkpoint when the chain has grown by the configured
        interval since the last seal."""
        every = self.checkpoint_every
        if every is not None and self._state.chained % every == 0:
            self.checkpoint_v2()

    # Chain-owned fields a caller-supplied body may never set itself.
    # The frame citation is chain-owned for the same reason the schema
    # is: a record does not get to choose the frame it claims.
    _RESERVED_FIELDS = frozenset(
        {"schema", "seq", "prev_hash", "entry_hash", "frame_id", "frame_hash"}
    )

    def record_entry(self, fields: dict[str, Any]) -> dict:
        """Append a caller-shaped entry (e.g. a freeze_manifest or
        test_run body from chancellor.receipts) under the same chain
        discipline as record(): the log stamps schema/seq/prev_hash/
        entry_hash and the governing frame's citation, and the entry
        is fsynced before state advances. Returns the stamped entry
        as written."""
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
            **_receipts.current_frame_fields(),
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
        self._maybe_seal()
        return entry

    def _sidecar_has_v2(self) -> bool:
        if not self.checkpoint_path.exists():
            return False
        for line in self.checkpoint_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                schema = _receipts.checkpoint_payload(json.loads(line)).get("schema")
            except Exception:
                continue
            if schema == _receipts.CHECKPOINT_SCHEMA_V2:
                return True
        return False

    def checkpoint(self) -> dict:
        """Sign a Merkle checkpoint over every chained entry so far and
        append it to the checkpoint sidecar. Returns the envelope. A
        sidecar that already holds a v2 checkpoint never takes a v1 one
        (the verifier rejects that order), so the checkpoint is written as
        v2 in that case."""
        if self._sidecar_has_v2():
            return self.checkpoint_v2()
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
        policy: ActionPolicy | None = None,
    ):
        self.audit_log = audit_log
        self.approver = approver
        self.human_id = human_id
        self._policy = policy if policy is not None else DEFAULT_POLICY

    @property
    def policy(self) -> ActionPolicy:
        """The policy table in force (read-only: the policy's tables are
        immutable mappings, and this attribute has no setter)."""
        return self._policy

    def authorize(self, request: EscalationRequest) -> Decision:
        """Decide a gate request and receipt the decision.

        The class is decided by the policy table (ActionPolicy), not by
        the requester: a declared class can only tighten it, and a
        request the table cannot classify is denied. The receipt carries
        the decided class and, separately, what was declared.

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
                refusal_state=REFUSAL_APPROVER_ERROR,
            )
        self._record(decision)
        return decision

    def note(
        self,
        *,
        node_id: str | None,
        action: str,
        approved: bool,
        rationale: str,
        refusal_state: str | None = None,
        tool: str | None = None,
    ) -> Decision:
        """Receipt a node-level event that is not a gated action: a node
        that declared no action, or one that failed before its gate."""
        request = EscalationRequest(
            action=action,
            action_class=ActionClass.NONE,
            node_id=node_id,
            tool=tool,
        )
        decision = Decision(
            request,
            approved,
            "policy",
            rationale,
            time.time(),
            refusal_state=refusal_state,
        )
        self._record(decision)
        return decision

    def record_outcome(self, fields: dict[str, Any]) -> None:
        """Write a tool_outcome entry (see receipts.tool_outcome_fields)
        onto the hash chain. Record-or-halt like every decision."""
        if self.audit_log is None:
            return
        try:
            self.audit_log.record_entry(fields)
        except Exception as exc:
            raise AuditWriteError(
                f"audit write failed for the outcome of call "
                f"{fields.get('call_id')!r} on {fields.get('tool')!r} "
                f"(record-or-halt): {type(exc).__name__}: {exc}"
            ) from exc

    def _record(self, decision: Decision) -> None:
        if self.audit_log is None:
            return
        try:
            self.audit_log.record(decision)
        except Exception as exc:
            raise AuditWriteError(
                f"audit write failed for gate decision on "
                f"{decision.request.action!r} — decision NOT in effect "
                f"(record-or-halt): {type(exc).__name__}: {exc}"
            ) from exc

    def _decide(self, request: EscalationRequest) -> Decision:
        classification = self.policy.classify(request)
        declared = request.action_class
        declared_text: str | None
        if declared is None:
            declared_text = None
        elif isinstance(declared, ActionClass):
            declared_text = declared.value
        elif isinstance(declared, str):
            declared_text = declared
        else:
            declared_text = repr(declared)
        decided = replace(
            request,
            action_class=classification.action_class,
            declared_class=declared_text,
        )
        if classification.denied_reason is not None:
            return Decision(
                decided,
                False,
                "policy",
                classification.denied_reason,
                time.time(),
                refusal_state=REFUSAL_UNCLASSIFIED,
            )
        if classification.action_class not in HUMAN_GATES:
            return Decision(
                decided,
                True,
                "policy",
                f"{classification.action_class.value} is auto-approved by policy",
                time.time(),
            )
        if self.approver is None:
            # Fail-closed: no human attached -> the gate does not open.
            return Decision(
                decided,
                False,
                "policy",
                "human gate with no approver attached — denied (fail-closed)",
                time.time(),
                refusal_state=REFUSAL_NO_APPROVER,
            )
        approved, rationale = self.approver(decided)
        return Decision(
            decided,
            bool(approved),
            self.human_id,
            rationale,
            time.time(),
            refusal_state=None if approved else REFUSAL_APPROVER_DECLINED,
        )
