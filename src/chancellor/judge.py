"""The Judge — a separate caller that produces rubric scores.

Score provenance (Council AM-7iii, the eighth seam): workers never grade
themselves. Scores enter `grader.grade()` only from this module (or from
deterministic instruments). The judge is a *different model variant* than
the worker it grades — same-model self-grading is refused at construction
when the worker model is declared.

Protocol per criterion (Scout 3 §A7, in the order the evidence supports):
  * one criterion per call — never all criteria in one call;
  * reason before score — the model emits a one-sentence justification
    first, then a final line `SCORE: <number>`;
  * 2–3 anchored exemplars per criterion sit in the prompt ("this is a 3
    on reversibility, because…").

Identity & caching (freeze rule, Scout 3 §A7.4): the judge is identified
by a content hash — the PIN — over (model, rubric, exemplars, prompt
template version). Once calibration passes, the pin is frozen for the
reported run; any change is a new pin and restarts calibration.
Responses are cached by (subject_id, proposal, criterion, prompt-hash),
so calibration iterations re-ask only what changed (Scout 3 §A7.5).

Fail-closed: an unparseable or out-of-range judge reply raises
JudgeError. The judge never invents a score to keep a run moving.

INTEGRATION INTERFACE (for the orchestrator provenance cut):
    judge = Judge(client, model="muse-wonder-1.0", rubric=RUBRIC,
                  exemplars=EXEMPLARS, worker_model="muse-spark-1.3",
                  cache=JudgeCache(path=...))          # pin via judge.pin
    scores: dict[str, float] = judge.score_proposal(
        subject_id=node.id, proposal=artifact_text,
        contexts={"stakeholder_coverage": "<gold list context>"})
    result = grade(rubric, scores)                    # existing grader
    # or in one step: result = judge.grade_proposal(subject_id, text, ...)
Contexts are per-criterion scoring-key material (e.g. the hidden gold
stakeholder list for coverage). They go to the judge only, never to any
responder prompt.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from .api_client import ChatMessage, MetaModelClient
from .grader import GradeResult, Rubric, grade

JUDGE_PROMPT_VERSION = "chancellor-judge-v1"

_SCORE_RE = re.compile(r"SCORE:\s*([0-9]+(?:\.[0-9]+)?)")


class JudgeError(RuntimeError):
    """The judge produced no usable score. Always fatal to the grading
    call — never caught and replaced with a default (fail-closed)."""


@dataclass
class Exemplar:
    """One anchored exemplar for a criterion: a proposal excerpt, the
    score it earns, and why."""

    criterion: str
    score: float
    excerpt: str
    rationale: str


@dataclass
class CriterionJudgment:
    criterion: str
    score: float
    reason: str
    cached: bool = False
    pin: str = ""


def _canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class JudgeCache:
    """Response cache keyed by (subject, proposal, criterion, prompt-hash).

    In-memory by default; pass a path for a JSON file that persists
    across calibration iterations. Values are plain dicts so the cache
    file stays inspectable.
    """

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._data: dict[str, dict] = {}
        if self.path and self.path.exists():
            self._data = json.loads(self.path.read_text(encoding="utf-8"))

    @staticmethod
    def make_key(
        subject_id: str, proposal: str, criterion: str, prompt_hash: str
    ) -> str:
        return _sha(
            _canonical(
                {
                    "subject": subject_id,
                    "proposal": _sha(proposal),
                    "criterion": criterion,
                    "prompt": prompt_hash,
                }
            )
        )

    def get(self, key: str) -> dict | None:
        return self._data.get(key)

    def put(self, key: str, value: dict) -> None:
        self._data[key] = value
        if self.path:
            self.path.write_text(json.dumps(self._data, indent=1), encoding="utf-8")

    def __len__(self) -> int:
        return len(self._data)


class Judge:
    def __init__(
        self,
        client: MetaModelClient,
        model: str,
        rubric: Rubric,
        exemplars: list[Exemplar] | None = None,
        worker_model: str | None = None,
        cache: JudgeCache | None = None,
        max_tokens: int = 400,
    ):
        if worker_model is not None and worker_model == model:
            raise ValueError(
                f"judge model {model!r} equals the worker model — self-grading "
                "is refused (declare a different judge variant)"
            )
        self.client = client
        self.model = model
        self.rubric = rubric
        self.max_tokens = max_tokens
        self.cache = cache if cache is not None else JudgeCache()
        self._exemplars: dict[str, list[Exemplar]] = {}
        for ex in exemplars or []:
            self._exemplars.setdefault(ex.criterion, []).append(ex)
        known = {c.name for c in rubric.criteria}
        stray = set(self._exemplars) - known
        if stray:
            raise ValueError(f"exemplars for unknown criteria: {sorted(stray)}")
        self.stats = {"calls": 0, "cache_hits": 0}
        self._pin = _sha(
            _canonical(
                {
                    "prompt_version": JUDGE_PROMPT_VERSION,
                    "model": model,
                    "rubric": {
                        "name": rubric.name,
                        "pass_mark": rubric.pass_mark,
                        "revise_mark": rubric.revise_mark,
                        "criteria": [
                            {
                                "name": c.name,
                                "weight": c.weight,
                                "max": c.max_score,
                                "description": c.description,
                            }
                            for c in rubric.criteria
                        ],
                    },
                    "exemplars": sorted(
                        (
                            {
                                "criterion": e.criterion,
                                "score": e.score,
                                "excerpt": e.excerpt,
                                "rationale": e.rationale,
                            }
                            for e in exemplars or []
                        ),
                        key=lambda d: (d["criterion"], d["score"]),
                    ),
                }
            )
        )

    @property
    def pin(self) -> str:
        """Content hash identifying this exact judge configuration."""
        return self._pin

    # -- prompt construction -------------------------------------------
    def _prompt(self, criterion, proposal: str, context: str = "") -> tuple[str, str]:
        crit = next(c for c in self.rubric.criteria if c.name == criterion)
        system = (
            "You are a strict evaluator for a governance harness. You score "
            "ONE criterion of a proposed remedy. You are not the author of "
            "the proposal and you gain nothing from its success. Judge the "
            "substance of the remedy, never its prose style, length, or "
            "confidence. Reply with exactly one sentence of justification, "
            "then a final line of the form SCORE: <number>."
        )
        lines = [
            f"Criterion: {crit.name} (0 to {crit.max_score:g})",
            f"What it measures: {crit.description}",
        ]
        anchors = sorted(self._exemplars.get(crit.name, []), key=lambda e: e.score)
        if anchors:
            lines.append("Anchored exemplars (excerpt -> score, and why):")
            for ex in anchors:
                lines.append(f'  [{ex.score:g}] "{ex.excerpt}" — {ex.rationale}')
        if context:
            lines.append(
                f"Scoring-key context (not shown to the proposal's author):\n{context}"
            )
        lines.append(f"Proposal to score:\n{proposal}")
        lines.append("Give your one-sentence justification, then the SCORE line.")
        return system, "\n".join(lines)

    # -- scoring ---------------------------------------------------------
    def score_criterion(
        self, subject_id: str, proposal: str, criterion: str, context: str = ""
    ) -> CriterionJudgment:
        if criterion not in {c.name for c in self.rubric.criteria}:
            raise JudgeError(
                f"unknown criterion {criterion!r} for rubric {self.rubric.name!r}"
            )
        crit = next(c for c in self.rubric.criteria if c.name == criterion)
        system, user = self._prompt(criterion, proposal, context)
        prompt_hash = _sha(system + "\n" + user)
        key = JudgeCache.make_key(subject_id, proposal, criterion, prompt_hash)
        hit = self.cache.get(key)
        if hit is not None:
            self.stats["cache_hits"] += 1
            return CriterionJudgment(
                criterion,
                float(hit["score"]),
                hit["reason"],
                cached=True,
                pin=self._pin,
            )
        resp = self.client.chat(
            self.model,
            [ChatMessage("system", system), ChatMessage("user", user)],
            max_tokens=self.max_tokens,
        )
        self.stats["calls"] += 1
        matches = _SCORE_RE.findall(resp.text or "")
        if not matches:
            raise JudgeError(
                f"judge returned no SCORE line for criterion {criterion!r} "
                f"(subject {subject_id!r}); refusing to invent one"
            )
        score = float(matches[-1])
        if score < 0 or score > crit.max_score:
            raise JudgeError(
                f"judge score {score} outside 0..{crit.max_score} for criterion "
                f"{criterion!r} (subject {subject_id!r}) — refusing to grade"
            )
        reason = " ".join(
            ln.strip()
            for ln in (resp.text or "").splitlines()
            if ln.strip() and not ln.strip().upper().startswith("SCORE:")
        ).strip()
        self.cache.put(key, {"score": score, "reason": reason, "model": self.model})
        return CriterionJudgment(criterion, score, reason, pin=self._pin)

    def score_proposal(
        self, subject_id: str, proposal: str, contexts: dict[str, str] | None = None
    ) -> dict[str, float]:
        """One judge call per criterion. Returns a scores dict in exactly
        the shape `grader.grade(rubric, scores)` consumes."""
        contexts = contexts or {}
        return {
            c.name: self.score_criterion(
                subject_id, proposal, c.name, contexts.get(c.name, "")
            ).score
            for c in self.rubric.criteria
        }

    def grade_proposal(
        self, subject_id: str, proposal: str, contexts: dict[str, str] | None = None
    ) -> GradeResult:
        """score_proposal + the existing grader, in one step."""
        return grade(self.rubric, self.score_proposal(subject_id, proposal, contexts))
