"""Interception layer — gate-capable tools run through Chancellor.

A tool that can spend, send, publish, destroy, or use a credential is
registered with a ToolBroker and invoked through it. For every call the
broker classifies the tool from the policy table, asks the Gatekeeper
BEFORE anything executes, and only then runs the tool with exactly the
arguments that were approved. Each call leaves a ledger record: what was
approved (class, argument digest) and what ran (argument digest, result
digest).

``reconcile`` compares the ledger with what a node reported. Any
disagreement between what was approved and what ran, or between what a
worker says it did and what went through the broker, is a mismatch, and
the runner halts on it.

Scope, stated plainly: the broker can only see calls made through it. A
worker that holds a direct handle to a gate-capable tool is outside this
layer; keep such handles out of workers and give them the broker.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from . import receipts
from .escalation import (
    REFUSAL_UNCLASSIFIED,
    ActionClass,
    EscalationRequest,
    Gatekeeper,
)

Tool = Callable[..., Any]


class ToolDenied(RuntimeError):
    """A brokered call was refused before execution."""


def digest(value: object) -> str:
    """Stable sha256 over a value's canonical JSON (repr for values JSON
    cannot carry)."""
    blob = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=repr
    ).encode("utf-8")
    return receipts.sha256_hex(blob)


@dataclass
class InterceptRecord:
    node_id: str
    tool: str
    action_class: str
    approved_args_sha256: str
    approved: bool
    started: bool = False
    executed_args_sha256: str | None = None
    result_sha256: str | None = None
    error: str | None = None


@dataclass
class ToolBroker:
    gatekeeper: Gatekeeper
    tools: dict[str, Tool] = field(default_factory=dict)
    effects: dict[str, tuple[str, ...]] = field(default_factory=dict)
    ledger: list[InterceptRecord] = field(default_factory=list)

    def register(self, name: str, fn: Tool, *, effects: tuple[str, ...] = ()) -> None:
        """Make a tool available through the broker. ``effects`` adds
        effect axes on top of whatever the policy table says for the
        tool's name; they can only make the decided class stricter."""
        self.tools[name.strip().lower()] = fn
        self.effects[name.strip().lower()] = tuple(effects)

    def mark(self) -> int:
        """A position in the ledger; pass it to reconcile to look only at
        calls made after this point."""
        return len(self.ledger)

    def has_tool(self, name: object) -> bool:
        return isinstance(name, str) and name.strip().lower() in self.tools

    def call(
        self,
        node_id: str,
        tool: str,
        args: Mapping[str, Any] | None = None,
        *,
        action: str | None = None,
        detail: str = "",
        cost_usd: float | None = None,
    ) -> Any:
        """Check, then run. Raises ToolDenied when the call is refused;
        the tool does not execute in that case."""
        key = tool.strip().lower()
        call_args = dict(args or {})
        args_digest = digest(call_args)
        request = EscalationRequest(
            action=action or f"call {key}",
            detail=detail,
            cost_usd=cost_usd,
            node_id=node_id,
            tool=key,
            effects=self.effects.get(key, ()),
            args_sha256=args_digest,
        )
        fn = self.tools.get(key)
        if fn is None:
            decision = self.gatekeeper.note(
                node_id=node_id,
                action=request.action,
                approved=False,
                rationale=f"tool {key!r} is not registered with the broker — denied",
                refusal_state=REFUSAL_UNCLASSIFIED,
                tool=key,
            )
            self.ledger.append(
                InterceptRecord(
                    node_id,
                    key,
                    ActionClass.UNCLASSIFIED.value,
                    args_digest,
                    approved=False,
                )
            )
            raise ToolDenied(decision.rationale)
        decision = self.gatekeeper.authorize(request)
        record = InterceptRecord(
            node_id,
            key,
            str(decision.request.action_class.value)
            if isinstance(decision.request.action_class, ActionClass)
            else ActionClass.UNCLASSIFIED.value,
            args_digest,
            approved=decision.approved,
        )
        self.ledger.append(record)
        if not decision.approved:
            raise ToolDenied(decision.rationale)
        # Run with a private copy of exactly what was approved, after
        # re-checking it still matches the approved digest.
        run_args = copy.deepcopy(call_args)
        record.executed_args_sha256 = digest(run_args)
        if record.executed_args_sha256 != args_digest:
            record.error = "arguments changed between approval and execution"
            raise ToolDenied(record.error)
        record.started = True
        try:
            result = fn(**run_args)
        except Exception as exc:
            record.error = f"{type(exc).__name__}: {exc}"
            raise
        record.result_sha256 = digest(result)
        return result

    def reconcile(
        self,
        node_id: str,
        since: int,
        declared: EscalationRequest | None = None,
    ) -> list[str]:
        """Mismatches between what was approved and what ran for this
        node's calls since ``since``, and between the node's declared
        action and the ledger. Empty means everything agrees."""
        mismatches: list[str] = []
        mine = [r for r in self.ledger[since:] if r.node_id == node_id]
        for r in mine:
            if r.started and not r.approved:
                mismatches.append(f"{r.tool}: ran without approval")
            if r.started and r.executed_args_sha256 != r.approved_args_sha256:
                mismatches.append(
                    f"{r.tool}: ran with arguments that were not approved"
                )
            if r.executed_args_sha256 is not None and not r.started:
                mismatches.append(f"{r.tool}: execution refused after approval")
        if declared is not None and self.has_tool(declared.tool):
            tool = str(declared.tool).strip().lower()
            matching = [r for r in mine if r.tool == tool and r.approved and r.started]
            if not matching:
                mismatches.append(
                    f"{tool}: declared by the worker but no approved call went "
                    "through the broker"
                )
            elif declared.args_sha256 is not None and not any(
                r.approved_args_sha256 == declared.args_sha256 for r in matching
            ):
                mismatches.append(
                    f"{tool}: declared arguments differ from the approved call"
                )
        return mismatches
