"""T1 property tests — task-graph invariants: lifecycle legality,
persistence round-trip, resume reconciliation (seeded randomized,
stdlib-only; see test_grader_properties for why)."""

import json
import random

import pytest

from chancellor.task_graph import (
    SCHEMA_VERSION,
    IllegalTransitionError,
    NodeStatus,
    TaskGraph,
)

CASES = 100


def _random_dag(rng: random.Random, n: int | None = None) -> TaskGraph:
    n = n or rng.randint(1, 8)
    g = TaskGraph(f"g-{rng.random()}")
    for i in range(n):
        deps = [f"n{j}" for j in range(i) if rng.random() < 0.35]
        g.task(f"n{i}", f"Node {i}", depends_on=deps)
    return g


# -- lifecycle ---------------------------------------------------------------


def test_terminal_states_are_terminal():
    g = TaskGraph("t")
    g.task("a", "A")
    g.task("b", "B")
    g.complete("a", output="done")
    for op in (
        lambda g=g: g.complete("a"),
        lambda g=g: g.fail("a", "again"),
        lambda g=g: g.block("a", "again"),
        lambda g=g: g.requeue("a", "again"),
        lambda g=g: g.start("a"),
    ):
        with pytest.raises(IllegalTransitionError):
            op()
    g.fail("b", "boom")
    for op in (
        lambda g=g: g.complete("b"),
        lambda g=g: g.fail("b", "again"),
        lambda g=g: g.requeue("b", "again"),
        lambda g=g: g.start("b"),
    ):
        with pytest.raises(IllegalTransitionError):
            op()


def test_blocked_cannot_complete_directly():
    g = TaskGraph("t")
    g.task("a", "A")
    g.start("a")
    g.block("a", "gate denied")
    with pytest.raises(IllegalTransitionError):
        g.complete("a")
    # The one legal exit from BLOCKED is requeue (gate re-evaluation).
    g.requeue("a", "approver attached")
    assert g.nodes["a"].status is NodeStatus.PENDING


def test_attempt_cap_enforced_at_start():
    g = TaskGraph("t")
    g.task("a", "A", max_attempts=2)
    g.start("a")
    g.requeue("a", "revise")
    g.start("a")
    g.requeue("a", "revise")
    with pytest.raises(ValueError):
        g.start("a")  # third dispatch would exceed the cap
    assert g.nodes["a"].attempts == 2


def test_status_lifecycle_random_walks():
    """Random operation walks: a terminal state is absorbing — once a
    node is DONE or FAILED, every further operation on it raises."""
    rng = random.Random(4242)
    for _ in range(CASES):
        g = _random_dag(rng, n=1)
        node = g.nodes["n0"]
        ops = [
            lambda g=g: g.start("n0"),
            lambda g=g: g.complete("n0"),
            lambda g=g: g.fail("n0", "x"),
            lambda g=g: g.block("n0", "x"),
            lambda g=g: g.requeue("n0", "x"),
        ]
        for _ in range(rng.randint(1, 12)):
            was_terminal = node.status in (
                NodeStatus.DONE,
                NodeStatus.FAILED,
                NodeStatus.SKIPPED,
            )
            try:
                rng.choice(ops)()
            except ValueError:
                continue  # illegal transition or attempt cap: refused
            assert not was_terminal, (
                f"an operation escaped terminal state {node.status}"
            )


# -- persistence ---------------------------------------------------------------


def test_persistence_roundtrip_random_graphs(tmp_path):
    rng = random.Random(13)
    for i in range(CASES):
        g = _random_dag(rng)
        # Complete a dependency-closed prefix so statuses vary legally.
        for node in list(g.nodes.values()):
            if (
                all(g.nodes[d].status is NodeStatus.DONE for d in node.depends_on)
                and rng.random() < 0.6
            ):
                g.complete(
                    node.id,
                    output={"text": f"out-{node.id}"},
                    grade=float(rng.randint(0, 100)),
                )
        path = tmp_path / f"s{i}.json"
        g.save(path)
        g2 = TaskGraph.load(path)
        assert set(g2.nodes) == set(g.nodes)
        for nid, node in g.nodes.items():
            other = g2.nodes[nid]
            assert other.status is node.status
            assert other.output == node.output
            assert other.grade == node.grade
            assert other.attempts == node.attempts
            assert other.max_attempts == node.max_attempts
            assert other.requires_grade == node.requires_grade


def test_save_is_atomic_and_versioned(tmp_path):
    g = _random_dag(random.Random(1), n=3)
    path = tmp_path / "state.json"
    g.save(path)
    data = json.loads(path.read_text())
    assert data["schema_version"] == SCHEMA_VERSION
    # No temp debris left behind by the atomic write.
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
    # A second save replaces cleanly.
    g.complete("n0", output="x")
    g.save(path)
    assert TaskGraph.load(path).nodes["n0"].status is NodeStatus.DONE


def test_load_refuses_future_schema(tmp_path):
    path = tmp_path / "future.json"
    path.write_text(
        json.dumps({"schema_version": SCHEMA_VERSION + 99, "name": "x", "nodes": []})
    )
    with pytest.raises(ValueError):
        TaskGraph.load(path)


def test_load_accepts_legacy_unversioned_state(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "name": "old",
                "nodes": [
                    {"id": "a", "title": "A", "status": "done", "output": "kept"}
                ],
            }
        )
    )
    g = TaskGraph.load(path)
    assert g.nodes["a"].status is NodeStatus.DONE
    assert g.nodes["a"].attempts == 0


# -- resume reconciliation -------------------------------------------------------


def test_resume_requeues_interrupted_node(tmp_path):
    g = TaskGraph("t")
    g.task("a", "A")
    g.task("b", "B", depends_on=["a"])
    g.complete("a")
    g.start("b")  # dispatched, then the process "dies" mid-run
    path = tmp_path / "s.json"
    g.save(path)
    g2 = TaskGraph.load(path)
    node = g2.nodes["b"]
    assert node.status is NodeStatus.PENDING
    assert node.attempts == 2  # the interrupted dispatch was counted
    assert "requeued" in g2.resume_report["b"]
    assert g2.nodes["a"].status is NodeStatus.DONE


def test_resume_fails_node_at_attempt_cap(tmp_path):
    g = TaskGraph("t")
    g.task("a", "A", max_attempts=1)
    g.start("a")  # attempts = 1 = cap; die mid-run
    path = tmp_path / "s.json"
    g.save(path)
    g2 = TaskGraph.load(path)
    assert g2.nodes["a"].status is NodeStatus.FAILED
    assert "cap" in g2.resume_report["a"]


def test_resume_keeps_failed_terminal_and_names_blocked(tmp_path):
    g = TaskGraph("t")
    g.task("a", "A")
    g.task("b", "B")
    g.task("c", "C")
    g.fail("a", "boom")
    g.start("b")
    g.block("b", "gate denied")
    path = tmp_path / "s.json"
    g.save(path)
    g2 = TaskGraph.load(path)
    assert g2.nodes["a"].status is NodeStatus.FAILED
    assert "terminal" in g2.resume_report["a"]
    assert g2.nodes["b"].status is NodeStatus.BLOCKED
    assert "blocked" in g2.resume_report["b"]
    assert set(g2.resume_report) == {"a", "b", "c"}  # every node named


def test_resume_invariants_random_graphs(tmp_path):
    """After load, no node is RUNNING, every node has a disposition,
    and DONE nodes are never resurrected."""
    rng = random.Random(77)
    for i in range(50):
        g = _random_dag(rng)
        for node in g.nodes.values():
            roll = rng.random()
            try:
                if roll < 0.3:
                    g.complete(node.id, output="x")
                elif roll < 0.4:
                    g.start(node.id)  # leave RUNNING = interrupted
                elif roll < 0.5:
                    g.fail(node.id, "x")
            except (IllegalTransitionError, ValueError):
                pass
        path = tmp_path / f"r{i}.json"
        g.save(path)
        before_done = {n.id for n in g.nodes.values() if n.status is NodeStatus.DONE}
        g2 = TaskGraph.load(path)
        assert all(n.status is not NodeStatus.RUNNING for n in g2.nodes.values())
        assert set(g2.resume_report) == set(g2.nodes)
        for nid in before_done:
            assert g2.nodes[nid].status is NodeStatus.DONE
