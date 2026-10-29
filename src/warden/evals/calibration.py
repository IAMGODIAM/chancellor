"""Suite A calibration — agreement statistics, the sealed scoring key,
and the calibration run itself.

Doctrine (Scout 3 §A6/A7; Council AM-9v):
  * The judge is trusted only insofar as it agrees with a hand-scored
    key. Report ALL of: quadratic-weighted Cohen's kappa per criterion,
    unweighted kappa on the verdict band, Spearman rho on totals, and
    MAE on totals. Raw % agreement is never reported alone.
  * Every statistic prints WITH its interval (bootstrap percentile CI
    and SE). A gate passed at kappa 0.71 +/- 0.13 does not wear the
    clothes of one passed at 0.71 +/- 0.03.
  * The calibration gate: per-criterion weighted kappa >= 0.6 (floor)
    with >= 0.7 on at least 3 of 4 criteria, verdict-band kappa >= 0.6,
    Spearman rho >= 0.8.
  * The ceiling rule: the judge cannot be more reliable than the key.
    The key here is ONE human; its self-agreement (blind re-score of 12
    references after >= 24h) is measured with the same machinery
    (compare_keys) and reported beside the judge's numbers.

THE KEY: `empty_key()` returns the scoring template with every score
set to None. Those scores are authored ONLY by the human scorer's pass
— no code in this repo fills them in. `validate_key` refuses an
incomplete key, and `run_calibration` refuses to run against one.
"""
from __future__ import annotations

import json
import math
import random
import statistics
from dataclasses import dataclass

from ..grader import Rubric, grade
from ..judge import Judge
from .suite_a import NORMATIVE_RUBRIC
from .suite_a_bank import scenario_by_id
from .suite_a_references import QUALITIES, REFERENCES, ReferenceProposal

GATE = {"kappa_floor": 0.6, "kappa_high": 0.7, "kappa_high_count": 3,
        "band_kappa": 0.6, "rho": 0.8, "self_agreement_kappa": 0.7}

_BOOTSTRAP_B = 1000
_BOOTSTRAP_SEED = 20261029


class KeyIncompleteError(ValueError):
    """The calibration key is missing scores/rationales. Fail-closed:
    calibration does not run against a partial key."""


# ---------------------------------------------------------------------
# The sealed key: template, validation, (de)serialization
# ---------------------------------------------------------------------
# Key shape: {(scenario_id, quality): {criterion: {"score": float|None,
#                                                  "rationale": str}}}

def empty_key(rubric: Rubric = NORMATIVE_RUBRIC) -> dict:
    """The scoring template. Every score is None — the human scorer
    authors them; nothing in this codebase ever fills them in."""
    return {
        ref.key: {c.name: {"score": None, "rationale": ""}
                  for c in rubric.criteria}
        for ref in REFERENCES
    }


def validate_key(key: dict, rubric: Rubric = NORMATIVE_RUBRIC) -> None:
    problems: list[str] = []
    expected = {ref.key for ref in REFERENCES}
    for item in sorted(expected - set(key)):
        problems.append(f"missing key entry {item}")
    for item in sorted(set(key) - expected):
        problems.append(f"unexpected key entry {item}")
    for item in sorted(expected & set(key)):
        for crit in rubric.criteria:
            cell = key[item].get(crit.name)
            if cell is None:
                problems.append(f"{item} criterion {crit.name}: missing")
                continue
            score, why = cell.get("score"), (cell.get("rationale") or "").strip()
            if score is None:
                problems.append(f"{item} criterion {crit.name}: score not authored")
            elif not isinstance(score, (int, float)) or isinstance(score, bool) \
                    or score < 0 or score > crit.max_score or math.isnan(score):
                problems.append(f"{item} criterion {crit.name}: score {score!r} invalid")
            if not why:
                problems.append(f"{item} criterion {crit.name}: rationale empty")
    if problems:
        raise KeyIncompleteError(
            f"calibration key incomplete ({len(problems)} problems): "
            + "; ".join(problems[:12])
            + ("; ..." if len(problems) > 12 else ""))


def key_scores(key: dict, rubric: Rubric = NORMATIVE_RUBRIC) -> dict[tuple, dict[str, float]]:
    """Extract {item: {criterion: score}} from a validated key."""
    validate_key(key, rubric)
    return {item: {c.name: float(key[item][c.name]["score"]) for c in rubric.criteria}
            for item in key}


def key_to_json(key: dict) -> str:
    flat = {f"{sid}|{q}": cells for (sid, q), cells in sorted(key.items())}
    return json.dumps(flat, indent=1)


def key_from_json(text: str) -> dict:
    flat = json.loads(text)
    return {tuple(k.split("|", 1)): v for k, v in flat.items()}


# ---------------------------------------------------------------------
# Agreement statistics (stdlib only)
# ---------------------------------------------------------------------

def _bin(score: float, max_score: float = 10.0) -> int:
    return max(0, min(int(max_score), int(round(score))))


def weighted_kappa(a: list[float], b: list[float], max_score: float = 10.0) -> float:
    """Quadratic-weighted Cohen's kappa over ordinal bins 0..max_score."""
    if len(a) != len(b) or not a:
        raise ValueError("weighted_kappa needs two non-empty, equal-length series")
    k = int(max_score) + 1
    obs = [[0.0] * k for _ in range(k)]
    for x, y in zip(a, b):
        obs[_bin(x, max_score)][_bin(y, max_score)] += 1.0
    n = float(len(a))
    rows = [sum(r) for r in obs]
    cols = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    num = den = 0.0
    for i in range(k):
        for j in range(k):
            w = 1.0 - ((i - j) / (k - 1)) ** 2
            num += w * obs[i][j]          # observed weighted agreement (counts)
            den += w * rows[i] * cols[j] / n  # chance-expected weighted agreement
    if den == n:
        # Chance-expected agreement is total: both raters pile onto one
        # identical category, so agreement is perfect by construction.
        return 1.0
    return (num - den) / (n - den)


def cohen_kappa(a: list, b: list) -> float:
    """Unweighted Cohen's kappa for categorical labels (verdict bands)."""
    if len(a) != len(b) or not a:
        raise ValueError("cohen_kappa needs two non-empty, equal-length series")
    n = len(a)
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    labels = set(a) | set(b)
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if expected == 1.0:
        return 1.0
    return (agree - expected) / (1.0 - expected)


def _ranks(xs: list[float]) -> list[float]:
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for t in range(i, j + 1):
            ranks[order[t]] = avg
        i = j + 1
    return ranks


def spearman(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or len(a) < 2:
        raise ValueError("spearman needs two series of length >= 2")
    ra, rb = _ranks(a), _ranks(b)
    ma, mb = statistics.fmean(ra), statistics.fmean(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    if den == 0.0:
        return 1.0 if ra == rb else 0.0
    return num / den


def _bootstrap(stat, pairs: list, b: int = _BOOTSTRAP_B) -> tuple[float, float]:
    """Percentile CI + SE for a statistic over paired observations."""
    rng = random.Random(_BOOTSTRAP_SEED)
    n = len(pairs)
    vals: list[float] = []
    for _ in range(b):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        try:
            v = stat(sample)
        except (ValueError, ZeroDivisionError):
            continue
        if isinstance(v, float) and math.isnan(v):
            continue
        vals.append(v)
    if len(vals) < b // 2:
        return (float("nan"), float("nan")), float("nan")
    vals.sort()
    lo = vals[int(0.025 * len(vals))]
    hi = vals[min(len(vals) - 1, int(0.975 * len(vals)))]
    return (round(lo, 3), round(hi, 3)), round(statistics.pstdev(vals), 3)


def _with_interval(stat, pairs) -> dict:
    point = stat(pairs)
    ci, se = _bootstrap(stat, pairs)
    return {"value": round(point, 3), "ci95": ci, "se": se, "n": len(pairs)}


def _band(total: float, rubric: Rubric) -> str:
    if total >= rubric.pass_mark:
        return "pass"
    if total >= rubric.revise_mark:
        return "revise"
    return "fail"


@dataclass
class ScorePair:
    item: tuple                       # (scenario_id, quality) or any hashable id
    a: dict[str, float]               # rater A per-criterion scores
    b: dict[str, float]               # rater B per-criterion scores


def compare_score_sets(pairs: list[ScorePair], rubric: Rubric = NORMATIVE_RUBRIC) -> dict:
    """Full agreement report between two raters over the same items.

    Used for judge-vs-key (calibration) AND key-vs-key (the ceiling
    rule's self-agreement) — same machinery, honestly labeled by caller.
    """
    if not pairs:
        raise ValueError("no score pairs to compare")
    per_criterion: dict[str, dict] = {}
    for crit in rubric.criteria:
        series = [(p.a[crit.name], p.b[crit.name]) for p in pairs]
        per_criterion[crit.name] = _with_interval(
            lambda s: weighted_kappa([x for x, _ in s], [y for _, y in s]), series)
    totals = []
    for p in pairs:
        totals.append((grade(rubric, p.a).total, grade(rubric, p.b).total))
    band = _with_interval(
        lambda s: cohen_kappa([_band(x, rubric) for x, _ in s],
                              [_band(y, rubric) for _, y in s]), totals)
    rho = _with_interval(
        lambda s: spearman([x for x, _ in s], [y for _, y in s]), totals)
    mae = round(statistics.fmean(abs(x - y) for x, y in totals), 3)
    kappas = {name: d["value"] for name, d in per_criterion.items()}
    gate = {
        "kappa_floor_ok": all(v >= GATE["kappa_floor"] for v in kappas.values()),
        "kappa_high_ok": sum(1 for v in kappas.values() if v >= GATE["kappa_high"])
                         >= GATE["kappa_high_count"],
        "band_kappa_ok": band["value"] >= GATE["band_kappa"],
        "rho_ok": rho["value"] >= GATE["rho"],
    }
    gate["passes"] = all(gate.values())
    return {
        "per_criterion_weighted_kappa": per_criterion,
        "verdict_band_kappa": band,
        "spearman_rho_totals": rho,
        "mae_totals": mae,
        "gate": gate,
        "gate_thresholds": dict(GATE),
    }


def compare_keys(key_a: dict, key_b: dict, rubric: Rubric = NORMATIVE_RUBRIC) -> dict:
    """Ceiling-rule check: one key against another (e.g. the Day-6 blind
    re-score of 12). Only items scored in BOTH keys are compared."""
    sa, sb = key_scores(key_a, rubric), key_scores(key_b, rubric)
    common = sorted(set(sa) & set(sb))
    if not common:
        raise ValueError("the two keys share no scored items")
    report = compare_score_sets([ScorePair(i, sa[i], sb[i]) for i in common], rubric)
    report["items_compared"] = len(common)
    report["self_agreement_ok"] = (
        all(d["value"] >= GATE["self_agreement_kappa"]
            for d in report["per_criterion_weighted_kappa"].values()))
    return report


# ---------------------------------------------------------------------
# The calibration run
# ---------------------------------------------------------------------

def coverage_context(scenario_id: str) -> dict[str, str]:
    """Scoring-key context handed to the JUDGE (never to a responder):
    the hidden gold stakeholder list, for the coverage criterion."""
    from .suite_a_gold import gold_stakeholders  # sealed module; judge-side only
    gold = gold_stakeholders(scenario_by_id(scenario_id))
    return {"stakeholder_coverage":
            "Materially affected parties (the full scoring key — the "
            "proposal's author was shown only a partial list): "
            + "; ".join(gold)}


def run_calibration(judge: Judge, key: dict, rubric: Rubric = NORMATIVE_RUBRIC,
                    references: list[ReferenceProposal] = REFERENCES) -> dict:
    """Score every reference proposal with the judge and compare against
    the completed human key. Refuses an incomplete key (fail-closed)."""
    human = key_scores(key, rubric)
    pairs: list[ScorePair] = []
    for ref in references:
        judged = judge.score_proposal(
            f"{ref.scenario_id}:{ref.quality}", ref.text,
            contexts=coverage_context(ref.scenario_id))
        pairs.append(ScorePair(ref.key, human[ref.key], judged))
    report = compare_score_sets(pairs, rubric)
    report["judge_pin"] = judge.pin
    report["judge_model"] = judge.model
    report["references"] = len(references)
    report["qualities"] = list(QUALITIES)
    return report
