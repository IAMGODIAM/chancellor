"""Judge module: separate caller, one criterion per call, reason before
score, pin + cache, fail-closed parsing, self-grading refused."""

import re

import pytest

from chancellor.api_client import ChatResponse, MetaModelClient, fake_transport
from chancellor.grader import OUTPUT_RUBRIC
from chancellor.judge import Exemplar, Judge, JudgeCache, JudgeError

SCORES = {"correctness": 8.0, "completeness": 6.0, "clarity": 7.0, "safety": 9.0}


def scripted_transport(scores, calls):
    def _t(model, messages, **kwargs):
        calls.append(messages)
        user = messages[-1].content
        crit = re.search(r"Criterion: (\w+)", user).group(1)
        return ChatResponse(
            text=f"Adequate on {crit}, with gaps noted.\nSCORE: {scores[crit]}",
            model=model,
            usage={"prompt_tokens": 10, "completion_tokens": 5},
        )

    return _t


def make_judge(calls, **kw):
    client = MetaModelClient(transport=scripted_transport(SCORES, calls))
    return Judge(client, model="muse-wonder-1.0", rubric=OUTPUT_RUBRIC, **kw)


def test_score_proposal_shape_feeds_grader():
    calls = []
    judge = make_judge(calls)
    scores = judge.score_proposal("node-1", "A worker output.")
    assert scores == SCORES
    result = judge.grade_proposal("node-1", "A worker output.")
    assert result.rubric == OUTPUT_RUBRIC.name
    assert 0 <= result.total <= 100
    # one call per criterion, no more
    assert len(calls) == len(OUTPUT_RUBRIC.criteria)


def test_one_criterion_per_call_and_reason_before_score():
    calls = []
    judge = make_judge(calls)
    j = judge.score_criterion("n", "text", "clarity")
    assert j.score == 7.0 and "Adequate" in j.reason
    user = calls[0][-1].content
    assert user.count("Criterion:") == 1  # exactly one criterion in the prompt


def test_pin_stable_and_sensitive():
    j1, j2 = make_judge([]), make_judge([])
    assert j1.pin == j2.pin and len(j1.pin) == 64
    ex = [Exemplar("clarity", 3.0, "muddy text", "cannot be verified quickly")]
    assert make_judge([], exemplars=ex).pin != j1.pin
    client = MetaModelClient(transport=scripted_transport(SCORES, []))
    other = Judge(client, model="muse-spark-1.3", rubric=OUTPUT_RUBRIC)
    assert other.pin != j1.pin


def test_cache_hits_and_file_persistence(tmp_path):
    calls = []
    path = tmp_path / "judge-cache.json"
    judge = make_judge(calls, cache=JudgeCache(path))
    judge.score_proposal("n1", "same proposal")
    n_calls = len(calls)
    again = make_judge(calls, cache=JudgeCache(path))  # fresh instance, same file
    scores = again.score_proposal("n1", "same proposal")
    assert scores == SCORES
    assert len(calls) == n_calls  # second pass fully cached
    assert again.stats["cache_hits"] == len(OUTPUT_RUBRIC.criteria)


def test_unparseable_reply_fails_closed():
    client = MetaModelClient(
        transport=lambda m, msgs, **k: ChatResponse(text="no score here", model=m)
    )
    judge = Judge(client, model="muse-wonder-1.0", rubric=OUTPUT_RUBRIC)
    with pytest.raises(JudgeError):
        judge.score_criterion("n", "text", "clarity")


def test_out_of_range_score_fails_closed():
    client = MetaModelClient(
        transport=lambda m, msgs, **k: ChatResponse(text="Great.\nSCORE: 42", model=m)
    )
    judge = Judge(client, model="muse-wonder-1.0", rubric=OUTPUT_RUBRIC)
    with pytest.raises(JudgeError):
        judge.score_criterion("n", "text", "clarity")


def test_fake_transport_cannot_grade():
    # The offline fake never emits SCORE lines; the judge must refuse,
    # not invent (this is what keeps offline plumbing honest).
    client = MetaModelClient(transport=fake_transport)
    judge = Judge(client, model="muse-wonder-1.0", rubric=OUTPUT_RUBRIC)
    with pytest.raises(JudgeError):
        judge.score_proposal("n", "text")


def test_self_grading_refused():
    client = MetaModelClient(transport=scripted_transport(SCORES, []))
    with pytest.raises(ValueError):
        Judge(
            client,
            model="muse-spark-1.3",
            rubric=OUTPUT_RUBRIC,
            worker_model="muse-spark-1.3",
        )


def test_exemplars_land_in_prompt():
    calls = []
    ex = [
        Exemplar("clarity", 3.0, "an unverifiable muddle", "a reviewer cannot check it")
    ]
    judge = make_judge(calls, exemplars=ex)
    judge.score_criterion("n", "text", "clarity")
    assert "an unverifiable muddle" in calls[0][-1].content
