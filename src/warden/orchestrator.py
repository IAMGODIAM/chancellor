"""CrewRunner — walks the task graph under governance.

For each ready node, in dependency order:
  1. the assigned worker produces an artifact {"text": ..., "cost_usd": ...}
  2. the instrument panel checks the artifact — any failure (including an
     instrument error or a check that never answers) rejects it and
     HALTS the run, fail-closed
  3. if the artifact requests a gated action, the Gatekeeper decides —
     a denial blocks the node and halts the run for a human
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
In Warden, surprises stop work; they never flow downstream.

Score provenance (the eighth seam, Council AM-7iii): a runner may carry
a `score_provider` — in production, the Judge (warden.judge). When one
is set, graded nodes take their scores from the provider, computed over
the artifact's text; the artifact itself never carries scores. Without
a provider, the legacy artifact-carried scores remain the input (the
test-only paths use them), and a scores-less artifact still halts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .escalation import ActionClass, EscalationRequest, Gatekeeper
from .grader import Rubric, grade
from .instruments import InstrumentPanel
from .task_graph import AttemptCapError, NodeStatus, TaskGraph, TaskNode

# A worker maps a node -> artifact dict.
Worker = Callable[[TaskNode], dict]


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
    def __init__(self, graph: TaskGraph, workers: dict[str, Worker],
                 panel: InstrumentPanel | None = None,
                 rubric: Rubric | None = None,
                 gatekeeper: Gatekeeper | None = None,
                 state_path: str | Path | None = None,
                 score_provider: Callable | None = None):
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
        self.governed = False

    @classmethod
    def governed(cls, graph: TaskGraph, workers: dict[str, Worker],
                 *, panel: InstrumentPanel, rubric: Rubric,
                 gatekeeper: Gatekeeper,
                 state_path: str | Path | None = None,
                 score_provider: Callable | None = None) -> "CrewRunner":
        """The production constructor. All three governance layers are
        required, and the panel must be non-empty — a governed runner
        that cannot check, grade, or gate is a contradiction, and it is
        refused at construction, not discovered mid-run."""
        if panel is None:
            raise ValueError("governed runner requires an instrument panel")
        if len(panel) == 0:
            raise ValueError(
                "governed runner requires a NON-EMPTY instrument panel — "
                "an empty panel certifies nothing (fail-closed)")
        if rubric is None:
            raise ValueError("governed runner requires a rubric")
        if gatekeeper is None:
            raise ValueError("governed runner requires a gatekeeper")
        runner = cls(graph, workers, panel=panel, rubric=rubric,
                     gatekeeper=gatekeeper, state_path=state_path,
                     score_provider=score_provider)
        runner.governed = True
        return runner

    @classmethod
    def ungoverned(cls, graph: TaskGraph, workers: dict[str, Worker],
                   *, state_path: str | Path | None = None) -> "CrewRunner":
        """The named test-only path: a runner with no governance layers.
        Exists so Suite B's ungoverned arm is a deliberate construction,
        never an accident of omitted arguments."""
        return cls(graph, workers, state_path=state_path)

    def _persist(self) -> None:
        if self.state_path is not None:
            self.graph.save(self.state_path)

    def _fail_node(self, node: TaskNode, report: RunReport, reason: str) -> bool:
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
                    node.id, "requeued at resume: gate re-evaluation "
                             "(approver attached)")
                report.dispositions[node.id] = self.graph.nodes[node.id].disposition

    def run(self) -> RunReport:
        self.graph.validate()
        report = RunReport(graph_name=self.graph.name, governed=self.governed)
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
                    return report   # halted — fail-closed
            self._persist()
        return report

    # -- gate boundary ------------------------------------------------------

    def _coerce_request(self, node: TaskNode, raw: object) -> EscalationRequest:
        """Coerce an artifact's action into an EscalationRequest at the
        gate boundary. Action classes arrive as enum members or as
        strings (model output drifts in case and whitespace); a string
        is coerced through the enum and validated — a case-drifted
        "SPEND" must reach the human gate, never slip past it, and an
        unknown class is malformed. Raises ValueError on anything
        malformed; the caller turns that into a halt, never a crash."""
        if isinstance(raw, EscalationRequest):
            req = raw
            if req.node_id is None:
                req.node_id = node.id
            if not isinstance(req.action_class, ActionClass):
                req.action_class = self._coerce_class(req.action_class)
            return req
        if isinstance(raw, dict):
            data = dict(raw)
            if "action_class" in data:
                data["action_class"] = self._coerce_class(data["action_class"])
            try:
                return EscalationRequest(node_id=node.id, **data)
            except TypeError as exc:
                raise ValueError(f"malformed gate request: {exc}") from exc
        raise ValueError(
            f"malformed gate request: action must be a mapping or "
            f"EscalationRequest, got {type(raw).__name__}")

    @staticmethod
    def _coerce_class(value: object) -> ActionClass:
        if isinstance(value, ActionClass):
            return value
        if isinstance(value, str):
            try:
                return ActionClass(value.strip().lower())
            except ValueError:
                raise ValueError(f"unknown action_class: {value!r}") from None
        raise ValueError(
            f"action_class must be an ActionClass or string, "
            f"got {type(value).__name__}")

    # -- one node -------------------------------------------------------------

    def _run_node(self, node: TaskNode, report: RunReport) -> bool:
        """Returns False when the run must halt."""
        try:
            self.graph.start(node.id)
        except AttemptCapError as exc:
            return self._fail_node(node, report, str(exc))
        worker = self.workers.get(node.worker)
        if worker is None:
            return self._fail_node(
                node, report, f"unknown worker '{node.worker}'")
        try:
            artifact = worker(node)
        except Exception as exc:
            return self._fail_node(
                node, report, f"worker error: {type(exc).__name__}: {exc}")

        # Instruments — fail-closed.
        if self.panel is not None:
            panel_result = self.panel.run_all(artifact)
            if not panel_result.ok:
                return self._fail_node(
                    node, report,
                    f"instrument failure: {panel_result.halt_reason}")

        # Escalation gate — a denied gate blocks the node and halts the run.
        if self.gatekeeper is not None and isinstance(artifact, dict) and "action" in artifact:
            try:
                req = self._coerce_request(node, artifact["action"])
            except ValueError as exc:
                return self._fail_node(node, report, str(exc))
            try:
                decision = self.gatekeeper.authorize(req)
            except Exception as exc:
                # FAIL-CLOSED: a gatekeeper that raises has not approved
                # anything. The node blocks for a human; the run halts.
                # (The Gatekeeper's own audit write is Lane 2's surface;
                # the denial is receipted here in the persisted state.)
                self.graph.block(
                    node.id, f"gatekeeper error — denied (fail-closed): "
                             f"{type(exc).__name__}: {exc}")
                report.blocked.append(node.id)
                report.halted = True
                report.halt_reason = (
                    f"node {node.id}: gatekeeper error — denied "
                    f"(fail-closed): {exc}")
                self._persist()
                return False
            if not decision.approved:
                self.graph.block(node.id, f"gate denied: {decision.rationale}")
                report.blocked.append(node.id)
                report.halted = True
                report.halt_reason = f"node {node.id}: gate denied ({decision.rationale})"
                self._persist()
                return False

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
                        node, report,
                        f"scoring error: {type(exc).__name__}: {exc}")
            elif isinstance(artifact, dict) and "scores" in artifact:
                scores = artifact["scores"]
            else:
                return self._fail_node(
                    node, report,
                    "graded node produced no scores — refusing to accept "
                    "ungraded output (fail-closed)")
            try:
                result = grade(self.rubric, scores)
            except Exception as exc:  # any grading error halts — AM-10(iv)
                return self._fail_node(
                    node, report,
                    f"grading error: {type(exc).__name__}: {exc}")
            total = result.total
            if result.verdict == "fail":
                return self._fail_node(
                    node, report, f"graded {total} (fail) — below revise floor")
            if result.verdict == "revise":
                # Revise means revise: the node goes back for another
                # attempt instead of completing on a band that asked
                # for revision. The cap is the loop's exit.
                report.grades[node.id] = total
                if node.attempts >= node.max_attempts:
                    return self._fail_node(
                        node, report,
                        f"graded {total} (revise) — attempt cap exhausted "
                        f"({node.attempts}/{node.max_attempts}); "
                        "revision could not clear the bar")
                report.revised.append(node.id)
                self.graph.requeue(
                    node.id, f"grade {total} in revise band — requeued "
                             f"(attempt {node.attempts} of "
                             f"{node.max_attempts} spent)")
                self.graph.nodes[node.id].grade = total
                self._persist()
                return True

        stored = artifact
        if isinstance(artifact, dict) and isinstance(artifact.get("action"), EscalationRequest):
            a = artifact["action"]
            stored = dict(artifact)
            stored["action"] = {
                "action": a.action, "action_class": a.action_class.value,
                "detail": a.detail, "cost_usd": a.cost_usd,
                "gate": "decided — see audit log",
            }
        self.graph.complete(node.id, output=stored, grade=total)
        report.completed.append(node.id)
        if total is not None:
            report.grades[node.id] = total
        self._persist()
        return True
