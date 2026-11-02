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

Tool access (broker): with a ToolBroker attached, a worker that needs
tools is registered with brokered_worker() and receives a per-node
NodeTools handle — the only way it reaches a registered tool, and every
call through it is checked before the tool runs. The handle is revoked
when the worker returns. A worker that holds a raw tool handle of its own
is outside what the runner can see; reconcile halts a node whose
declared tool never went through the broker.

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
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import cast

from .escalation import (
    REFUSAL_NODE_FAILED,
    REFUSAL_RECONCILE_MISMATCH,
    REFUSAL_UNCLASSIFIED,
    ActionClass,
    EscalationRequest,
    Gatekeeper,
)
from .grader import Rubric, grade
from .instruments import InstrumentPanel
from .interception import NodeTools, ToolBroker
from .task_graph import AttemptCapError, NodeStatus, TaskGraph, TaskNode

# A worker maps a node -> artifact dict.
Worker = Callable[[TaskNode], dict]
# A worker that needs tools maps (node, NodeTools) -> artifact dict. It is
# wrapped with brokered_worker() so the runner knows to pass the handle.
BrokeredFn = Callable[[TaskNode, NodeTools], dict]


@dataclass(frozen=True)
class BrokeredWorker:
    """A worker that receives its tools only as a per-node NodeTools
    handle from the runner's broker."""

    fn: BrokeredFn

    def __call__(self, node: TaskNode, tools: NodeTools) -> dict:
        return self.fn(node, tools)


def brokered_worker(fn: BrokeredFn) -> BrokeredWorker:
    """Mark ``fn(node, tools)`` as a worker that takes broker-mediated
    tool access. Usable as a decorator."""
    return BrokeredWorker(fn)


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
        workers: Mapping[str, Worker | BrokeredWorker],
        panel: InstrumentPanel | None = None,
        rubric: Rubric | None = None,
        gatekeeper: Gatekeeper | None = None,
        state_path: str | Path | None = None,
        score_provider: Callable | None = None,
        broker: ToolBroker | None = None,
    ):
        """The low-level constructor. Every governance layer is optional
        here, which makes this the TEST-ONLY path — production code must
        use CrewRunner.governed().

        `score_provider`: optional callable (node, artifact) -> scores
        dict. When set, it — not the artifact — is where graded nodes'
        scores come from (score provenance: the Judge, in production)."""
        self.graph = graph
        self.workers = workers
        self.panel = panel
        self.rubric = rubric
        self.gatekeeper = gatekeeper
        self.state_path = Path(state_path) if state_path else None
        self.score_provider = score_provider
        self.broker = broker
        self.is_governed = False
        self._attempt_receipted = False
        self._broker_mark = 0

    @classmethod
    def governed(
        cls,
        graph: TaskGraph,
        workers: Mapping[str, Worker | BrokeredWorker],
        *,
        panel: InstrumentPanel,
        rubric: Rubric,
        gatekeeper: Gatekeeper,
        state_path: str | Path | None = None,
        score_provider: Callable | None = None,
        broker: ToolBroker | None = None,
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
        )
        runner.is_governed = True
        return runner

    @classmethod
    def ungoverned(
        cls,
        graph: TaskGraph,
        workers: Mapping[str, Worker | BrokeredWorker],
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

    def _gate(
        self, node: TaskNode, artifact: object, report: RunReport
    ) -> tuple[bool, EscalationRequest | None, EscalationRequest | None]:
        """The node's gate. Returns (proceed, decided request, declared
        request). Every path leaves a receipt: an action decision, "no
        action declared", or a denial naming why."""
        gatekeeper = self.gatekeeper
        assert gatekeeper is not None
        if not (isinstance(artifact, dict) and "action" in artifact):
            if node.inert or self._brokered_calls(node):
                gatekeeper.note(
                    node_id=node.id,
                    action=f"node {node.id}: no action declared",
                    approved=True,
                    rationale="no action declared — node declared inert by the "
                    "graph, or its actions went through the broker",
                )
                self._receipted()
                return True, None, None
            gatekeeper.note(
                node_id=node.id,
                action=f"node {node.id}: no action declared",
                approved=False,
                rationale="no action declared and the node is not declared inert "
                "— denied (fail-closed)",
                refusal_state=REFUSAL_UNCLASSIFIED,
            )
            self._receipted()
            self.graph.block(node.id, "gate denied: no action declared")
            report.blocked.append(node.id)
            report.halted = True
            report.halt_reason = (
                f"node {node.id}: gate denied (no action declared, fail-closed)"
            )
            self._persist()
            return False, None, None
        try:
            declared = self._coerce_request(node, artifact["action"])
        except ValueError as exc:
            self._fail_node(node, report, str(exc), refusal_state=REFUSAL_UNCLASSIFIED)
            return False, None, None
        if self.broker is not None and self.broker.has_tool(declared.tool):
            # A brokered tool was already checked, per call, before it
            # ran; the reconcile step compares the claim to the ledger.
            self._receipted()
            return True, declared, declared
        try:
            decision = gatekeeper.authorize(declared)
        except Exception as exc:
            # FAIL-CLOSED: a gatekeeper that raises has not approved
            # anything. The node blocks for a human; the run halts.
            self._receipted()
            self.graph.block(
                node.id,
                f"gatekeeper error — denied (fail-closed): {type(exc).__name__}: {exc}",
            )
            report.blocked.append(node.id)
            report.halted = True
            report.halt_reason = (
                f"node {node.id}: gatekeeper error — denied (fail-closed): {exc}"
            )
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

    def _brokered_calls(self, node: TaskNode) -> bool:
        broker = self.broker
        return broker is not None and any(
            r.node_id == node.id for r in broker.ledger[self._broker_mark :]
        )

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
        tools: NodeTools | None = None
        try:
            if isinstance(worker, BrokeredWorker):
                if self.broker is None:
                    raise RuntimeError(
                        "worker requires tool access but the runner has no "
                        "broker (fail-closed)"
                    )
                tools = self.broker.session(node.id)
                artifact = worker(node, tools)
            else:
                artifact = worker(node)
        except Exception as exc:
            return self._fail_node(
                node, report, f"worker error: {type(exc).__name__}: {exc}"
            )
        finally:
            if tools is not None:
                tools.revoke()

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
