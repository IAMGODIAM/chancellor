"""Explicit, durable task graphs.

A run is a DAG of TaskNodes. The graph validates itself (unknown deps,
cycles) before anything executes, computes which nodes are ready, and
serializes to JSON after every transition so a killed process can resume
from the last completed node.

Durability discipline (W1):
  * save() is atomic — temp file in the same directory, fsync, atomic
    rename, directory fsync. A kill mid-write can never corrupt the
    only copy of run state.
  * The state file carries a schema version; load() refuses a version
    newer than this code understands (fail-closed).
  * load() reconciles interrupted state: a node persisted RUNNING was
    dispatched but never resolved — it is requeued with its attempt
    counter incremented, or failed if its attempt cap is exhausted.
    FAILED is terminal. BLOCKED nodes hold until a runner with an
    approver attached re-evaluates them. Every node's disposition is
    named in graph.resume_report.
  * Status transitions are guarded: DONE, FAILED, and SKIPPED are
    terminal, and any transition outside the lifecycle table raises.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

SCHEMA_VERSION = 1

# Node defaults.
DEFAULT_MAX_ATTEMPTS = 3


class NodeStatus(StrEnum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    BLOCKED = "blocked"  # stopped at an escalation gate
    SKIPPED = "skipped"


class CycleError(ValueError):
    """Raised when the task graph contains a dependency cycle."""


class IllegalTransitionError(ValueError):
    """Raised when a node status transition is outside the lifecycle."""


class AttemptCapError(ValueError):
    """Raised when a node is started after its attempt cap is exhausted."""


# The lifecycle: which statuses each status may move to. DONE, FAILED,
# and SKIPPED are terminal — nothing leaves them. A failed node is never
# silently resurrected; a completed node never re-runs.
_TRANSITIONS: dict[NodeStatus, frozenset[NodeStatus]] = {
    NodeStatus.PENDING: frozenset(
        {
            NodeStatus.READY,
            NodeStatus.RUNNING,
            NodeStatus.DONE,
            NodeStatus.FAILED,
            NodeStatus.BLOCKED,
            NodeStatus.SKIPPED,
        }
    ),
    NodeStatus.READY: frozenset(
        {
            NodeStatus.PENDING,
            NodeStatus.RUNNING,
            NodeStatus.DONE,
            NodeStatus.FAILED,
            NodeStatus.BLOCKED,
            NodeStatus.SKIPPED,
        }
    ),
    NodeStatus.RUNNING: frozenset(
        {NodeStatus.PENDING, NodeStatus.DONE, NodeStatus.FAILED, NodeStatus.BLOCKED}
    ),
    NodeStatus.BLOCKED: frozenset({NodeStatus.PENDING}),
    NodeStatus.DONE: frozenset(),
    NodeStatus.FAILED: frozenset(),
    NodeStatus.SKIPPED: frozenset(),
}

TERMINAL_STATUSES = frozenset({NodeStatus.DONE, NodeStatus.FAILED, NodeStatus.SKIPPED})


@dataclass
class TaskNode:
    id: str
    title: str
    depends_on: list[str] = field(default_factory=list)
    worker: str = "agent"  # key into the runner's worker table
    status: NodeStatus = NodeStatus.PENDING
    output: object = None
    grade: float | None = None  # 0-100 rubric total, once graded
    error: str | None = None
    updated_at: float = 0.0
    attempts: int = 0  # dispatches begun, incl. interrupted
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    requires_grade: bool = True  # False = explicit ungraded-class node
    disposition: str | None = None  # last resume/lifecycle disposition

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "depends_on": list(self.depends_on),
            "worker": self.worker,
            "status": self.status.value,
            "output": self.output,
            "grade": self.grade,
            "error": self.error,
            "updated_at": self.updated_at,
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "requires_grade": self.requires_grade,
            "disposition": self.disposition,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TaskNode:
        return cls(
            id=d["id"],
            title=d["title"],
            depends_on=list(d.get("depends_on", [])),
            worker=d.get("worker", "agent"),
            status=NodeStatus(d.get("status", "pending")),
            output=d.get("output"),
            grade=d.get("grade"),
            error=d.get("error"),
            updated_at=d.get("updated_at", 0.0),
            attempts=int(d.get("attempts", 0)),
            max_attempts=int(d.get("max_attempts", DEFAULT_MAX_ATTEMPTS)),
            requires_grade=bool(d.get("requires_grade", True)),
            disposition=d.get("disposition"),
        )


class TaskGraph:
    def __init__(self, name: str = "run"):
        self.name = name
        self.nodes: dict[str, TaskNode] = {}
        # node id -> disposition, populated by load() reconciliation.
        self.resume_report: dict[str, str] = {}

    # -- construction ------------------------------------------------------
    def add(self, node: TaskNode) -> TaskNode:
        if node.id in self.nodes:
            raise ValueError(f"duplicate node id: {node.id}")
        self.nodes[node.id] = node
        return node

    def task(
        self,
        id: str,
        title: str,
        depends_on=None,
        worker: str = "agent",
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
        requires_grade: bool = True,
    ) -> TaskNode:
        return self.add(
            TaskNode(
                id=id,
                title=title,
                depends_on=list(depends_on or []),
                worker=worker,
                max_attempts=max_attempts,
                requires_grade=requires_grade,
            )
        )

    # -- validation ----------------------------------------------------------
    # CC 11 (radon) — one pass per invariant family: unknown deps,
    # then cycle coloring.
    def validate(self) -> None:
        for node in self.nodes.values():
            for dep in node.depends_on:
                if dep not in self.nodes:
                    raise ValueError(f"node {node.id} depends on unknown node {dep}")
        # Cycle detection via iterative DFS coloring.
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(self.nodes, WHITE)
        for start in self.nodes:
            if color[start] != WHITE:
                continue
            stack = [(start, iter(self.nodes[start].depends_on))]
            color[start] = GRAY
            path = [start]
            while stack:
                nid, it = stack[-1]
                advanced = False
                for dep in it:
                    if color[dep] == GRAY:
                        raise CycleError(
                            f"dependency cycle: {' -> '.join(path + [dep])}"
                        )
                    if color[dep] == WHITE:
                        color[dep] = GRAY
                        path.append(dep)
                        stack.append((dep, iter(self.nodes[dep].depends_on)))
                        advanced = True
                        break
                if not advanced:
                    color[nid] = BLACK
                    stack.pop()
                    path.pop()

    # -- lifecycle -------------------------------------------------------------
    def _set_status(self, node: TaskNode, new: NodeStatus) -> None:
        if new is node.status:
            if node.status in TERMINAL_STATUSES:
                raise IllegalTransitionError(
                    f"node {node.id}: {node.status.value} is terminal — "
                    f"it cannot transition again (not even to itself)"
                )
            return
        if new not in _TRANSITIONS[node.status]:
            raise IllegalTransitionError(
                f"node {node.id}: illegal transition {node.status.value} -> {new.value}"
            )
        node.status = new
        self._touch(node)

    def _touch(self, node: TaskNode) -> None:
        node.updated_at = time.time()

    def start(self, node_id: str) -> TaskNode:
        """Begin a dispatch: PENDING/READY -> RUNNING, attempt counted.
        Raises AttemptCapError if the node's attempt cap is exhausted —
        the counter is checked before the attempt is spent."""
        node = self.nodes[node_id]
        if node.attempts >= node.max_attempts:
            raise AttemptCapError(
                f"node {node_id}: attempt cap exhausted "
                f"({node.attempts}/{node.max_attempts})"
            )
        self._set_status(node, NodeStatus.RUNNING)
        node.attempts += 1
        node.error = None
        self._touch(node)
        return node

    def complete(self, node_id: str, output=None, grade: float | None = None) -> None:
        node = self.nodes[node_id]
        self._set_status(node, NodeStatus.DONE)
        node.output = output
        node.grade = grade
        node.error = None
        node.disposition = f"completed (attempt {node.attempts} of {node.max_attempts})"

    def fail(self, node_id: str, error: str) -> None:
        node = self.nodes[node_id]
        self._set_status(node, NodeStatus.FAILED)
        node.error = error
        node.disposition = f"failed: {error}"

    def block(self, node_id: str, reason: str) -> None:
        node = self.nodes[node_id]
        self._set_status(node, NodeStatus.BLOCKED)
        node.error = reason
        node.disposition = f"blocked: {reason}"

    def requeue(self, node_id: str, reason: str) -> None:
        """Return a node to PENDING for another attempt (revise verdict,
        crash reconciliation, gate re-evaluation). The caller owns the
        attempt-cap decision; the attempt itself is counted at start()."""
        node = self.nodes[node_id]
        self._set_status(node, NodeStatus.PENDING)
        node.error = None
        node.disposition = reason

    # -- scheduling ------------------------------------------------------------
    def ready(self) -> list[TaskNode]:
        """Pending nodes whose dependencies are all DONE. Marks them READY."""
        out = []
        for node in self.nodes.values():
            if node.status in (NodeStatus.PENDING, NodeStatus.READY) and all(
                self.nodes[d].status is NodeStatus.DONE for d in node.depends_on
            ):
                if node.status is NodeStatus.PENDING:
                    self._set_status(node, NodeStatus.READY)
                out.append(node)
        return out

    def is_complete(self) -> bool:
        return all(n.status is NodeStatus.DONE for n in self.nodes.values())

    def unfinished(self) -> list[TaskNode]:
        return [
            n
            for n in self.nodes.values()
            if n.status not in (NodeStatus.DONE, NodeStatus.SKIPPED)
        ]

    # -- persistence -------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        """Atomically persist: temp file in the same directory, fsync,
        os.replace, directory fsync. A kill at any point leaves either
        the old state or the new state — never a torn file."""
        path = Path(path)
        data = {
            "schema_version": SCHEMA_VERSION,
            "name": self.name,
            "nodes": [n.to_dict() for n in self.nodes.values()],
        }
        # Compact separators: the state file is machine-read (load is
        # format-agnostic); indent cost 1.6x the bytes and ~5x the
        # save time at N=1000 (both measured) for no reader.
        payload = json.dumps(data, separators=(",", ":"))
        tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
        try:
            with tmp.open("w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        finally:
            if tmp.exists():
                tmp.unlink()
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    @classmethod
    def load(cls, path: str | Path) -> TaskGraph:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        version = data.get("schema_version", 0)
        if not isinstance(version, int) or version > SCHEMA_VERSION:
            raise ValueError(
                f"state file schema_version {version!r} is newer than this "
                f"code understands ({SCHEMA_VERSION}) — refusing to load "
                "(fail-closed)"
            )
        graph = cls(name=data.get("name", "run"))
        for nd in data.get("nodes", []):
            graph.add(TaskNode.from_dict(nd))
        graph._reconcile_resume()
        return graph

    # CC 11 (radon) — one branch per on-disk node state; each state
    # reconciles independently of the others.
    def _reconcile_resume(self) -> None:
        """Reconcile state written by a process that may have died
        mid-flight. Names every node's disposition in resume_report."""
        report: dict[str, str] = {}
        for node in self.nodes.values():
            if node.status is NodeStatus.RUNNING:
                # Dispatched but never resolved: the interruption spends
                # the attempt whether or not start() got persisted.
                node.attempts += 1
                if node.attempts >= node.max_attempts:
                    self._set_status(node, NodeStatus.FAILED)
                    node.error = (
                        "attempt cap exhausted: interrupted "
                        "mid-run on the final attempt"
                    )
                    node.disposition = (
                        f"failed at resume: attempt cap exhausted "
                        f"({node.attempts}/{node.max_attempts})"
                    )
                else:
                    self._set_status(node, NodeStatus.PENDING)
                    node.error = None
                    node.disposition = (
                        f"requeued at resume: interrupted mid-run "
                        f"(attempt {node.attempts} of {node.max_attempts} spent)"
                    )
                report[node.id] = node.disposition
            elif node.status is NodeStatus.FAILED:
                detail = node.disposition or "failed before the interruption"
                report[node.id] = f"terminal: {detail} — not retried"
            elif node.status is NodeStatus.BLOCKED:
                node.disposition = (
                    "blocked: held at an escalation gate — re-evaluates "
                    "when a runner with an approver attached resumes it"
                )
                report[node.id] = node.disposition
            elif node.status is NodeStatus.DONE:
                report[node.id] = node.disposition or "done: kept"
            elif node.status is NodeStatus.SKIPPED:
                report[node.id] = node.disposition or "skipped: kept"
            else:
                report[node.id] = "pending: not yet run"
        self.resume_report = report
