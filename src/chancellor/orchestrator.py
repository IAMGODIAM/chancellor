"""CrewRunner — walks the task graph under governance.

For each ready node, in dependency order:
  1. the assigned worker produces an artifact {"text": ..., "cost_usd": ...}
  2. the instrument panel checks the artifact — any failure (including an
     instrument error or a check that never answers) rejects it and
     HALTS the run, fail-closed
  3. the Gatekeeper decides the node's action — classified from the
     policy table, never from the worker's say-so alone; a denial, an
     unclassifiable action, or a missing action (unless the graph
     declares the node inert) blocks the node and halts the run for a
     human. Every node leaves a receipt, including "no action declared"
     and failure before the gate. With a ToolBroker attached, a final
     reconcile step halts on any mismatch between what was approved and
     what ran
  4. the artifact is graded against the rubric — grading is not opt-in:
     a node either requires scores or declares itself ungraded on the
     graph; a scores-less artifact on a graded node halts the run.
     A "fail" verdict rejects the node; a "revise" verdict REQUEUES it
     (revise means revise) until its attempt cap, then fails it
  5. accepted outputs complete the node; run state persists to disk

Governance by construction (W1): production runs are built with
CrewRunner.governed(...), which REQUIRES a non-empty panel, a rubric,
and a gatekeeper. The plain constructor and CrewRunner.ungoverned(...)
are the test-only path — Suite B's ungoverned arm uses them deliberately,
and the RunReport of an ungoverned runner says so.

A worker that raises halts the run. A gatekeeper that raises is a DENY.
A malformed gate request halts the run — it never crashes out of it.
In Chancellor, surprises stop work; they never flow downstream.

Score provenance (the eighth seam, Council AM-7iii): a runner may carry
a `score_provider` — in production, the Judge (chancellor.judge). When one
is set, graded nodes take their scores from the provider, computed over
the artifact's text; the artifact itself never carries scores. Without
a provider, the legacy artifact-carried scores remain the input (the
test-only paths use them), and a scores-less artifact still halts.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from .escalation import (
    HUMAN_GATES,
    REFUSAL_BROKERED_DENIAL,
    REFUSAL_DECLARATION_MISMATCH,
    REFUSAL_INERT_VIOLATION,
    REFUSAL_NODE_FAILED,
    REFUSAL_RECONCILE_MISMATCH,
    REFUSAL_UNBROKERED_EFFECT,
    REFUSAL_UNCLASSIFIED,
    ActionClass,
    EscalationRequest,
    Gatekeeper,
    coerce_class,
    strictest,
)
from .grader import Rubric, grade
from .instruments import InstrumentPanel
from .interception import InterceptRecord, ObservedEffect, ToolBroker
from .task_graph import AttemptCapError, NodeStatus, TaskGraph, TaskNode

# A worker maps a node -> artifact dict.
Worker = Callable[[TaskNode], dict]

# An effect observer reports the side effects it can see for a node after
# the node's worker has run (for example by diffing a sandbox, a ledger
# or a mock service). The runner reconciles them against the broker.
EffectObserver = Callable[[TaskNode], Iterable[ObservedEffect]]


@dataclass
class RunReport:
    graph_name: str
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    revised: list[str] = field(default_factory=list)
    grades: dict[str, float] = field(default_factory=dict)
    # node id -> disposition, from load-time reconciliation and any
    # gate re-evaluations this run performed.
    dispositions: dict[str, str] = field(default_factory=dict)
    governed: bool = False
    halted: bool = False
    halt_reason: str | None = None

    @property
    def ok(self) -> bool:
        return not self.halted and not self.failed and not self.blocked


class CrewRunner:
    def __init__(
        self,
        graph: TaskGraph,
        workers: dict[str, Worker],
        panel: InstrumentPanel | None = None,
        rubric: Rubric | None = None,
        gatekeeper: Gatekeeper | None = None,
        state_path: str | Path | None = None,
        score_provider: Callable | None = None,
        broker: ToolBroker | None = None,
        effect_observers: Iterable[EffectObserver] = (),
        raw_tool_handles: Mapping[str, Collection[str]] | None = None,
    ):
        """The low-level constructor. Every governance layer is optional
        here, which makes this the TEST-ONLY path — production code must
        use CrewRunner.governed().

        `score_provider`: optional callable (node, artifact) -> scores
        dict. When set, it — not the artifact — is where graded nodes'
        scores come from (score provenance: the Judge, in production).

        `effect_observers`: callables (node) -> effects the runner can see
        for that node; each must correspond to an approved brokered call
        or the run halts. `raw_tool_handles`: worker name -> the tools that
        worker holds directly (not through the broker). A worker may also
        carry a `raw_tool_handles` attribute. A node whose worker holds any
        such handle cannot be marked inert."""
        self.graph = graph
        self.workers = workers
        self.panel = panel
        self.rubric = rubric
        self.gatekeeper = gatekeeper
        self.state_path = Path(state_path) if state_path else None
        self.score_provider = score_provider
        self.broker = broker
        self.effect_observers = tuple(effect_observers)
        self._raw_tool_handles = {
            name: frozenset(tools) for name, tools in (raw_tool_handles or {}).items()
        }
        self.is_governed = False
        self._attempt_receipted = False
        self._broker_mark = 0

    @classmethod
    def governed(
        cls,
        graph: TaskGraph,
        workers: dict[str, Worker],
        *,
        panel: InstrumentPanel,
        rubric: Rubric,
        gatekeeper: Gatekeeper,
        state_path: str | Path | None = None,
        score_provider: Callable | None = None,
        broker: ToolBroker | None = None,
        effect_observers: Iterable[EffectObserver] = (),
        raw_tool_handles: Mapping[str, Collection[str]] | None = None,
    ) -> CrewRunner:
        """The production constructor. All three governance layers are
        required, and the panel must be non-empty — a governed runner
        that cannot check, grade, or gate is a contradiction, and it is
        refused at construction, not discovered mid-run."""
        if panel is None:
            raise ValueError("governed runner requires an instrument panel")
        if len(panel) == 0:
            raise ValueError(
                "governed runner requires a NON-EMPTY instrument panel — "
                "an empty panel certifies nothing (fail-closed)"
            )
        if rubric is None:
            raise ValueError("governed runner requires a rubric")
        if gatekeeper is None:
            raise ValueError("governed runner requires a gatekeeper")
        runner = cls(
            graph,
            workers,
            panel=panel,
            rubric=rubric,
            gatekeeper=gatekeeper,
            state_path=state_path,
            score_provider=score_provider,
            broker=broker,
            effect_observers=effect_observers,
            raw_tool_handles=raw_tool_handles,
        )
        runner.is_governed = True
        if not runner.effect_observers and not runner._raw_tool_handles:
            logging.getLogger(__name__).warning(
                "governed runner has no effect observer or raw tool registration; "
                "effects outside the broker may not be detected"
            )
        return runner

    @classmethod
    def ungoverned(
        cls,
        graph: TaskGraph,
        workers: dict[str, Worker],
        *,
        state_path: str | Path | None = None,
    ) -> CrewRunner:
        """The named test-only path: a runner with no governance layers.
        Exists so Suite B's ungoverned arm is a deliberate construction,
        never an accident of omitted arguments."""
        return cls(graph, workers, state_path=state_path)

    def _persist(self) -> None:
        if self.state_path is not None:
            self.graph.save(self.state_path)

    def _fail_node(
        self,
        node: TaskNode,
        report: RunReport,
        reason: str,
        *,
        refusal_state: str = REFUSAL_NODE_FAILED,
        force_receipt: bool = False,
    ) -> bool:
        # Every node attempt leaves a receipt; one that fails before its
        # gate gets a denial receipt naming why.
        if self.gatekeeper is not None and (
            force_receipt or not self._attempt_receipted
        ):
            # The node is failing anyway; the halt stands if the write fails.
            with contextlib.suppress(Exception):
                self.gatekeeper.note(
                    node_id=node.id,
                    action=f"node {node.id}",
                    approved=False,
                    rationale=reason,
                    refusal_state=refusal_state,
                )
            self._attempt_receipted = True
        self.graph.fail(node.id, reason)
        report.failed.append(node.id)
        report.halted = True
        report.halt_reason = f"node {node.id}: {reason}"
        self._persist()
        return False

    def _reevaluate_blocked(self, report: RunReport) -> None:
        """On resume, a BLOCKED node whose gate can now be decided —
        this runner has a gatekeeper WITH an approver attached — is
        requeued so its worker re-runs and the gate re-decides. A gate
        with no approver leaves the node exactly where it was."""
        if self.gatekeeper is None or self.gatekeeper.approver is None:
            return
        for node in self.graph.nodes.values():
            if node.status is NodeStatus.BLOCKED:
                self.graph.requeue(
                    node.id,
                    "requeued at resume: gate re-evaluation (approver attached)",
                )
                # requeue() sets the disposition on the line above.
                report.dispositions[node.id] = cast(str, node.disposition)

    def run(self) -> RunReport:
        self.graph.validate()
        report = RunReport(graph_name=self.graph.name, governed=self.is_governed)
        report.dispositions.update(self.graph.resume_report)
        self._reevaluate_blocked(report)
        self._persist()
        if self._inert_handle_violations(report):
            return report
        while not self.graph.is_complete():
            ready = self.graph.ready()
            if not ready:
                stuck = [n.id for n in self.graph.unfinished()]
                report.halted = True
                report.halt_reason = f"no ready nodes; unfinished: {stuck}"
                break
            for node in ready:
                if not self._run_node(node, report):
                    return report  # halted — fail-closed
            # No per-wave persist: every _run_node exit path persists
            # after its last mutation (mutation-path verification,
            # council R9) — a wave-end write would rewrite identical
            # bytes.
        return report

    # -- gate boundary ------------------------------------------------------

    def _coerce_request(self, node: TaskNode, raw: object) -> EscalationRequest:
        """Coerce an artifact's action into an EscalationRequest at the
        gate boundary. The declared class is passed through untouched —
        the Gatekeeper's policy table decides the class, and a declared
        class it cannot read is denied there, with a receipt. The node id
        is always the runner's, never the worker's. Raises ValueError on
        a malformed request; the caller turns that into a halt."""
        if isinstance(raw, EscalationRequest):
            return replace(raw, node_id=node.id)
        if isinstance(raw, dict):
            data = dict(raw)
            data.pop("node_id", None)
            if "effects" in data:
                effects = data["effects"]
                data["effects"] = (
                    (effects,) if isinstance(effects, str) else tuple(effects or ())
                )
            try:
                return EscalationRequest(node_id=node.id, **data)
            except TypeError as exc:
                raise ValueError(f"malformed gate request: {exc}") from exc
        raise ValueError(
            f"malformed gate request: action must be a mapping or "
            f"EscalationRequest, got {type(raw).__name__}"
        )

    def _receipted(self) -> None:
        self._attempt_receipted = True

    def _deny_node(
        self,
        node: TaskNode,
        report: RunReport,
        *,
        action: str,
        rationale: str,
        refusal_state: str,
        tool: str | None = None,
    ) -> tuple[bool, EscalationRequest | None, EscalationRequest | None]:
        """Receipt a denial for the node, block it, and halt the run."""
        assert self.gatekeeper is not None
        self.gatekeeper.note(
            node_id=node.id,
            action=action,
            approved=False,
            rationale=rationale,
            refusal_state=refusal_state,
            tool=tool,
        )
        self._receipted()
        self.graph.block(node.id, f"gate denied: {rationale}")
        report.blocked.append(node.id)
        report.halted = True
        report.halt_reason = f"node {node.id}: gate denied ({rationale})"
        self._persist()
        return False, None, None

    def _node_rows(self, node: TaskNode) -> list[InterceptRecord]:
        broker = self.broker
        if broker is None:
            return []
        return broker.rows_for(node.id, self._broker_mark)

    def _brokered_class(self, rows: list[InterceptRecord]) -> ActionClass | None:
        """The class of what the node actually ran: the strictest class
        the policy table gives the brokered tools. Never taken from the
        worker."""
        assert self.gatekeeper is not None
        classes = [self.gatekeeper.policy.tool_class(r.tool) for r in rows]
        if not classes or any(c is None for c in classes):
            return None
        return strictest([c for c in classes if c is not None])

    def _declaration_mismatch(
        self, declared: EscalationRequest, rows: list[InterceptRecord]
    ) -> str | None:
        """Why the declared action does not match the brokered calls, or
        None when it does."""
        assert self.gatekeeper is not None
        brokered = self._brokered_class(rows)
        if brokered is None:
            return "a brokered tool has no class in the policy table"
        tools = {r.tool for r in rows}
        if declared.tool is not None and (
            not isinstance(declared.tool, str)
            or declared.tool.strip().lower() not in tools
        ):
            return (
                f"declared tool {declared.tool!r} is not among the brokered "
                f"calls {sorted(tools)}"
            )
        if declared.action_class is not None:
            declared_class = coerce_class(declared.action_class)
            if declared_class is not brokered:
                return (
                    f"declared class {declared.action_class!r} does not match "
                    f"the brokered class {brokered.value!r}"
                )
        effects = declared.effects
        for effect in (effects,) if isinstance(effects, str) else effects:
            effect_class = (
                self.gatekeeper.policy.effects.get(effect.strip().lower())
                if isinstance(effect, str)
                else None
            )
            if effect_class is None or strictest([effect_class, brokered]) is not (
                brokered
            ):
                return (
                    f"declared effect {effect!r} goes beyond the brokered "
                    f"class {brokered.value!r}"
                )
        return None

    def _gate(
        self, node: TaskNode, artifact: object, report: RunReport
    ) -> tuple[bool, EscalationRequest | None, EscalationRequest | None]:
        """The node's gate. Returns (proceed, decided request, declared
        request). Every path leaves a receipt: an action decision, "no
        action declared", or a denial naming why.

        The class of a brokered node comes from what it ran (the broker's
        ledger and the policy table). A declaration is checked against
        that and is denied on any mismatch. A node with no brokered call
        has only its declaration, which can add a human gate but never
        earns auto-approval."""
        gatekeeper = self.gatekeeper
        assert gatekeeper is not None
        rows = self._node_rows(node)
        if node.inert and rows:
            return self._deny_node(
                node,
                report,
                action=f"node {node.id}: brokered call on an inert node",
                rationale="node is marked inert but made brokered call(s) "
                f"({', '.join(sorted({r.tool for r in rows}))}) — denied",
                refusal_state=REFUSAL_INERT_VIOLATION,
            )
        denied = [r for r in rows if not r.approved]
        if denied:
            return self._deny_node(
                node,
                report,
                action=f"node {node.id}: brokered call was denied",
                rationale="a brokered call by this node was denied "
                f"({', '.join(sorted({r.tool for r in denied}))}); the node "
                "cannot complete — denied",
                refusal_state=REFUSAL_BROKERED_DENIAL,
            )
        if not (isinstance(artifact, dict) and "action" in artifact):
            if node.inert or rows:
                gatekeeper.note(
                    node_id=node.id,
                    action=f"node {node.id}: no action declared",
                    approved=True,
                    rationale="no action declared — node declared inert by the "
                    "graph, or its actions went through the broker",
                )
                self._receipted()
                return True, None, None
            return self._deny_node(
                node,
                report,
                action=f"node {node.id}: no action declared",
                rationale="no action declared and the node is not declared inert "
                "— denied",
                refusal_state=REFUSAL_UNCLASSIFIED,
            )
        try:
            declared = self._coerce_request(node, artifact["action"])
        except ValueError as exc:
            self._fail_node(node, report, str(exc), refusal_state=REFUSAL_UNCLASSIFIED)
            return False, None, None
        if rows:
            mismatch = self._declaration_mismatch(declared, rows)
            if mismatch is not None:
                return self._deny_node(
                    node,
                    report,
                    action=declared.action,
                    rationale=f"declared action does not match the brokered "
                    f"calls: {mismatch} — denied",
                    refusal_state=REFUSAL_DECLARATION_MISMATCH,
                    tool=declared.tool if isinstance(declared.tool, str) else None,
                )
            # The per-call receipts are the decisions; the node's class is
            # what the brokered tools are in the policy table.
            self._receipted()
            return (
                True,
                replace(declared, action_class=self._brokered_class(rows)),
                declared,
            )
        if self.broker is not None and self.broker.has_tool(declared.tool):
            return self._deny_node(
                node,
                report,
                action=declared.action,
                rationale=f"declared brokered tool {declared.tool!r} but no "
                "call went through the broker — denied",
                refusal_state=REFUSAL_DECLARATION_MISMATCH,
                tool=str(declared.tool),
            )
        classification = gatekeeper.policy.classify(declared)
        if (
            classification.denied_reason is None
            and classification.action_class not in HUMAN_GATES
        ):
            return self._deny_node(
                node,
                report,
                action=declared.action,
                rationale="the node declared an auto-approved action but made "
                "no brokered call; auto-approval needs a brokered call — denied",
                refusal_state=REFUSAL_DECLARATION_MISMATCH,
                tool=declared.tool if isinstance(declared.tool, str) else None,
            )
        try:
            decision = gatekeeper.authorize(declared)
        except Exception as exc:
            # A gatekeeper that raises has not approved anything. The
            # node blocks for a human; the run halts.
            self._receipted()
            self.graph.block(
                node.id,
                f"gatekeeper error — denied: {type(exc).__name__}: {exc}",
            )
            report.blocked.append(node.id)
            report.halted = True
            report.halt_reason = f"node {node.id}: gatekeeper error — denied: {exc}"
            self._persist()
            return False, None, declared
        self._receipted()
        if not decision.approved:
            self.graph.block(node.id, f"gate denied: {decision.rationale}")
            report.blocked.append(node.id)
            report.halted = True
            report.halt_reason = f"node {node.id}: gate denied ({decision.rationale})"
            self._persist()
            return False, decision.request, declared
        return True, decision.request, declared

    def _raw_handles_of(self, node: TaskNode) -> frozenset[str]:
        held = set(self._raw_tool_handles.get(node.worker, ()))
        worker = self.workers.get(node.worker)
        attr = getattr(worker, "raw_tool_handles", None)
        if isinstance(attr, (set, frozenset, list, tuple)):
            held.update(str(t) for t in attr)
        return frozenset(held)

    def _inert_handle_violations(self, report: RunReport) -> bool:
        """Receipt and halt on any inert node whose worker holds raw tool
        handles, before any worker runs. Returns True when it halted."""
        gatekeeper = self.gatekeeper
        if gatekeeper is None:
            return False
        for node in self.graph.nodes.values():
            held = self._raw_handles_of(node) if node.inert else frozenset()
            if not held:
                continue
            reason = (
                f"node is marked inert but its worker holds tool handle(s) "
                f"({', '.join(sorted(held))}) — refused"
            )
            gatekeeper.note(
                node_id=node.id,
                action=f"node {node.id}: inert with tool handles",
                approved=False,
                rationale=reason,
                refusal_state=REFUSAL_INERT_VIOLATION,
            )
            self.graph.block(node.id, f"gate denied: {reason}")
            report.blocked.append(node.id)
            report.halted = True
            report.halt_reason = f"node {node.id}: gate denied ({reason})"
            self._persist()
            return True
        return False

    def _unbrokered_effects(self, node: TaskNode) -> list[str]:
        """Side effects the observers can see for this node that no
        approved brokered call accounts for. An observer that fails is
        reported as an unverifiable effect."""
        problems: list[str] = []
        for observer in self.effect_observers:
            try:
                observed = list(observer(node))
            except Exception as exc:
                problems.append(f"effect observer failed: {type(exc).__name__}: {exc}")
                continue
            if self.broker is None:
                problems.extend(
                    f"{e.description or e.tool}: effect seen with no broker"
                    for e in observed
                )
            else:
                problems.extend(
                    self.broker.unbrokered(node.id, self._broker_mark, observed)
                )
        return problems

    # -- one node -------------------------------------------------------------

    # CC 25 (radon) — the governed path in one visible flow: check,
    # grade, gate, escalate, persist. Deliberately not scattered
    # across handlers; each branch is a governance outcome.
    def _run_node(self, node: TaskNode, report: RunReport) -> bool:
        """Returns False when the run must halt."""
        self._attempt_receipted = False
        self._broker_mark = self.broker.mark() if self.broker is not None else 0
        try:
            self.graph.start(node.id)
        except AttemptCapError as exc:
            return self._fail_node(node, report, str(exc))
        worker = self.workers.get(node.worker)
        if worker is None:
            return self._fail_node(node, report, f"unknown worker '{node.worker}'")
        try:
            artifact = worker(node)
        except Exception as exc:
            return self._fail_node(
                node, report, f"worker error: {type(exc).__name__}: {exc}"
            )

        # Effects the runner can see must each be accounted for by an
        # approved brokered call.
        if self.gatekeeper is not None and self.effect_observers:
            unbrokered = self._unbrokered_effects(node)
            if unbrokered:
                return self._fail_node(
                    node,
                    report,
                    "unbrokered effect — halted: " + "; ".join(unbrokered),
                    refusal_state=REFUSAL_UNBROKERED_EFFECT,
                    force_receipt=True,
                )

        # Instruments — fail-closed.
        if self.panel is not None:
            panel_result = self.panel.run_all(artifact)
            if not panel_result.ok:
                return self._fail_node(
                    node, report, f"instrument failure: {panel_result.halt_reason}"
                )

        # Escalation gate — every node is decided and receipted; a denied
        # or unclassifiable gate blocks the node and halts the run.
        decided: EscalationRequest | None = None
        if self.gatekeeper is not None:
            proceed, decided, declared = self._gate(node, artifact, report)
            if not proceed:
                return False
            if self.broker is not None:
                mismatches = self.broker.reconcile(node.id, self._broker_mark, declared)
                if mismatches:
                    return self._fail_node(
                        node,
                        report,
                        "reconcile mismatch — halted: " + "; ".join(mismatches),
                        refusal_state=REFUSAL_RECONCILE_MISMATCH,
                        force_receipt=True,
                    )

        # Grading — not opt-in. With a rubric set, a node either
        # requires scores or has declared itself ungraded on the graph.
        # Score provenance: with a score_provider set, scores come from
        # the provider (the Judge) over the artifact's content — the
        # artifact never carries them. Without one, the artifact's own
        # scores are the input, and their absence halts the run.
        total: float | None = None
        if self.rubric is not None and node.requires_grade:
            if self.score_provider is not None:
                try:
                    scores = self.score_provider(node, artifact)
                except Exception as exc:  # a scorer that cannot score halts
                    return self._fail_node(
                        node, report, f"scoring error: {type(exc).__name__}: {exc}"
                    )
            elif isinstance(artifact, dict) and "scores" in artifact:
                scores = artifact["scores"]
            else:
                return self._fail_node(
                    node,
                    report,
                    "graded node produced no scores — refusing to accept "
                    "ungraded output (fail-closed)",
                )
            try:
                result = grade(self.rubric, scores)
            except Exception as exc:  # any grading error halts — AM-10(iv)
                return self._fail_node(
                    node, report, f"grading error: {type(exc).__name__}: {exc}"
                )
            total = result.total
            if result.verdict == "fail":
                return self._fail_node(
                    node, report, f"graded {total} (fail) — below revise floor"
                )
            if result.verdict == "revise":
                # Revise means revise: the node goes back for another
                # attempt instead of completing on a band that asked
                # for revision. The cap is the loop's exit.
                report.grades[node.id] = total
                if node.attempts >= node.max_attempts:
                    return self._fail_node(
                        node,
                        report,
                        f"graded {total} (revise) — attempt cap exhausted "
                        f"({node.attempts}/{node.max_attempts}); "
                        "revision could not clear the bar",
                    )
                report.revised.append(node.id)
                self.graph.requeue(
                    node.id,
                    f"grade {total} in revise band — requeued "
                    f"(attempt {node.attempts} of "
                    f"{node.max_attempts} spent)",
                )
                self.graph.nodes[node.id].grade = total
                self._persist()
                return True

        stored = artifact
        if isinstance(artifact, dict) and isinstance(
            artifact.get("action"), EscalationRequest
        ):
            a = decided if decided is not None else artifact["action"]
            stored = dict(artifact)
            stored["action"] = {
                "action": a.action,
                "action_class": a.action_class.value
                if isinstance(a.action_class, ActionClass)
                else a.action_class,
                "detail": a.detail,
                "cost_usd": a.cost_usd,
                "gate": "decided — see audit log",
            }
        self.graph.complete(node.id, output=stored, grade=total)
        report.completed.append(node.id)
        if total is not None:
            report.grades[node.id] = total
        self._persist()
        return True
