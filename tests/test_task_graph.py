import pytest

from warden.task_graph import CycleError, NodeStatus, TaskGraph


def _graph():
    g = TaskGraph("t")
    g.task("a", "A")
    g.task("b", "B", depends_on=["a"])
    g.task("c", "C", depends_on=["a"])
    g.task("d", "D", depends_on=["b", "c"])
    return g


def test_ready_flow():
    g = _graph()
    assert [n.id for n in g.ready()] == ["a"]
    g.complete("a", output="done")
    assert {n.id for n in g.ready()} == {"b", "c"}
    g.complete("b"); g.complete("c")
    assert [n.id for n in g.ready()] == ["d"]
    g.complete("d")
    assert g.is_complete()


def test_unknown_dependency_rejected():
    g = TaskGraph()
    g.task("x", "X", depends_on=["ghost"])
    with pytest.raises(ValueError):
        g.validate()


def test_cycle_detected():
    g = TaskGraph()
    g.task("a", "A", depends_on=["b"])
    g.task("b", "B", depends_on=["a"])
    with pytest.raises(CycleError):
        g.validate()


def test_persistence_roundtrip(tmp_path):
    g = _graph()
    g.complete("a", output={"text": "hi"}, grade=88.5)
    path = tmp_path / "state.json"
    g.save(path)
    g2 = TaskGraph.load(path)
    assert g2.nodes["a"].status is NodeStatus.DONE
    assert g2.nodes["a"].grade == 88.5
    assert [n.id for n in g2.ready()] == ["b"] or {n.id for n in g2.ready()} == {"b", "c"}
