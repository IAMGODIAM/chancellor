"""Policy Engine — SPEC §2 (Chancellor, Governor of Operations).

Standing orders, encoded as executable rules, evaluated *before* the
act. A rule is data (the §2.1 schema) plus this evaluator; packs are
refused at load when they cannot cite their founding failure or
standing order — the razor (§1). Verdicts:

  allow / allow:local      the act proceeds
  route:<target>           the act proceeds, elsewhere
  queue:<target>           the act waits (e.g. off-box target down)
  stage:<gate>             the act waits for a named human gate
  deny                     the act does not proceed

Gated classes (money, sends, submissions, publishes, deploys, state
changes) fail closed: an unavailable engine denies, never waves
through. Ungated classes proceed on a DEGRADED receipt — silence is
never a behavior (§2.1, §8).

Rule precedence is mechanical: among firing non-default rules the
highest ``priority`` wins; two different actions at the same top
priority are a *conflict* — the act stages for the Chairman with both
rules' receipts attached, because a contradiction in his orders is
his to resolve, not the engine's (§2.1).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import receipts as _receipts
from .governor_receipts import RECEIPT_KINDS, GovernorReceipts

GATED_CLASSES = frozenset(
    {"money", "send", "submission", "publish", "deploy", "state-change"}
)

_ACTION_RE = re.compile(
    r"^(allow|deny|allow:[a-z0-9-]+|route:[a-z0-9-]+|stage:[a-z0-9-]+"
    r"|queue:[a-z0-9-]+)$"
)
_YEAR_RE = re.compile(r"\b(19|20)\d\d\b")


class PackRefusal(ValueError):
    """A pack or rule failed admission (the razor, §2.1/A6)."""


@dataclass(frozen=True)
class Rule:
    id: str
    pack: str
    founded_by: str
    act_classes: tuple[str, ...]
    action: str
    receipt: str
    override: str
    measured_by: str
    when: dict = field(default_factory=dict)
    phase: str | None = None
    priority: int = 0
    default: bool = False
    summary: str = ""
    terms: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Pack:
    name: str
    version: str
    founded_by: str
    rules: tuple[Rule, ...]
    config: dict = field(default_factory=dict)


@dataclass
class Verdict:
    action: str
    rule_ids: list[str] = field(default_factory=list)
    receipt_ids: list[str] = field(default_factory=list)
    gated: bool = False
    degraded: bool = False
    detail: str = ""
    conflict: tuple[str, str] | None = None
    override_by: str | None = None
    unmet_preconditions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action": self.action,
            "rules": self.rule_ids,
            "receipts": self.receipt_ids,
            "gated": self.gated,
            "degraded": self.degraded,
            "detail": self.detail,
            "conflict": list(self.conflict) if self.conflict else None,
            "override_by": self.override_by,
            "unmet_preconditions": self.unmet_preconditions,
        }


def _founding_ok(value: object) -> bool:
    """A founding citation names its failure/order AND its date."""
    return (
        isinstance(value, str)
        and len(value.strip()) >= 10
        and _YEAR_RE.search(value) is not None
    )


def validate_rule(raw: dict, pack_name: str) -> Rule:
    """One rule against the §2.1 schema. Every field is required;
    a rule without ``founded_by`` is refused — that refusal is the
    razor test (A6) at the loader."""
    rid = raw.get("id")
    if not isinstance(rid, str) or "." not in rid:
        raise PackRefusal(f"rule in pack {pack_name!r} has no usable id: {rid!r}")
    if not _founding_ok(raw.get("founded_by")):
        raise PackRefusal(
            f"rule {rid}: refused — no dated founding citation "
            "(SPEC §2.1: founded_by names the failure or standing "
            "order, dated, that created this rule)"
        )
    classes = raw.get("act_classes") or (
        [raw["act_class"]] if raw.get("act_class") else []
    )
    if not classes:
        raise PackRefusal(f"rule {rid}: no act_classes")
    action = raw.get("action")
    if not isinstance(action, str) or not _ACTION_RE.match(action):
        raise PackRefusal(f"rule {rid}: unusable action {action!r}")
    receipt = raw.get("receipt")
    if receipt not in RECEIPT_KINDS:
        raise PackRefusal(f"rule {rid}: receipt kind {receipt!r} not in SPEC §5.1")
    override = raw.get("override")
    if override not in {"chairman-by-name", "none"}:
        raise PackRefusal(f"rule {rid}: override must be chairman-by-name | none")
    measured_by = raw.get("measured_by")
    if not isinstance(measured_by, str) or not measured_by.strip():
        raise PackRefusal(f"rule {rid}: measured_by must name fact + instrument")
    return Rule(
        id=rid,
        pack=pack_name,
        founded_by=raw["founded_by"],
        act_classes=tuple(classes),
        action=action,
        receipt=receipt,
        override=override,
        measured_by=measured_by,
        when=raw.get("when") or {},
        phase=raw.get("phase"),
        priority=int(raw.get("priority", 0)),
        default=bool(raw.get("default", False)),
        summary=raw.get("summary", ""),
        terms=raw.get("terms") or {},
    )


def load_pack(raw: dict, receipts: GovernorReceipts | None = None) -> Pack:
    """Validate a pack dict. On refusal the refusal itself is
    receipted (A6) when a receipts sink is attached, then raised."""
    try:
        name = raw.get("name")
        if not isinstance(name, str) or not name:
            raise PackRefusal("pack has no name")
        if not _founding_ok(raw.get("founded_by")):
            raise PackRefusal(
                f"pack {name}: refused — a pack that cannot name its "
                "founding failure is refused (SPEC §1, the razor)"
            )
        rules = tuple(validate_rule(r, name) for r in raw.get("rules") or [])
        if not rules:
            raise PackRefusal(f"pack {name}: no rules")
        return Pack(
            name=name,
            version=str(raw.get("version", "0")),
            founded_by=raw["founded_by"],
            rules=rules,
            config=raw.get("config") or {},
        )
    except PackRefusal as exc:
        if receipts is not None:
            receipts.mint(
                "policy-verdict",
                {
                    "outcome": "pack-refused",
                    "pack": raw.get("name"),
                    "reason": str(exc),
                },
            )
        raise


def load_pack_file(path: str | Path, receipts: GovernorReceipts | None = None) -> Pack:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return load_pack(raw, receipts=receipts)


# ------------------------------------------------------------ conditions
def _compare(op: str, value: Any, operand: Any) -> bool:
    """One comparison; a type-mismatched descriptor field reads as
    no-match, never as an engine crash — a malformed descriptor is a
    failed measurement, and failed measurements do not fire rules."""
    try:
        if op == "gt":
            return bool(value > operand)
        if op == "gte":
            return bool(value >= operand)
        if op == "lt":
            return bool(value < operand)
        if op == "lte":
            return bool(value <= operand)
        if op == "ne":
            return bool(value != operand)
        if op == "in":
            return bool(value in operand)
    except TypeError:
        return False
    return False


def _field_match(cond: Any, value: Any, present: bool) -> bool:
    if isinstance(cond, dict):
        for op, operand in cond.items():
            if op == "exists":
                if present != bool(operand):
                    return False
            elif not present:
                return False
            elif op in {"gt", "gte", "lt", "lte", "ne", "in"}:
                if not _compare(op, value, operand):
                    return False
            else:
                return False
        return True
    if isinstance(cond, list):
        return present and value in cond
    return present and value == cond


def matches(when: dict, descriptor: dict) -> bool:
    """The condition mini-language: a dict is an AND of field
    conditions, with ``any`` / ``all`` / ``not`` combinators. A
    field-to-field comparison is written
    ``{"<field>": {"gt_field": "<other>"}}`` and is resolved here."""
    for key, cond in when.items():
        if key == "any":
            if not any(matches(c, descriptor) for c in cond):
                return False
        elif key == "all":
            if not all(matches(c, descriptor) for c in cond):
                return False
        elif key == "not":
            if matches(cond, descriptor):
                return False
        else:
            present = key in descriptor
            value = descriptor.get(key)
            if isinstance(cond, dict) and "gt_field" in cond:
                other = cond["gt_field"]
                if not present or other not in descriptor:
                    return False
                if not _compare("gt", value, descriptor[other]):
                    return False
                rest = {k: v for k, v in cond.items() if k != "gt_field"}
                if rest and not _field_match(rest, value, present):
                    return False
            elif not _field_match(cond, value, present):
                return False
    return True


@dataclass
class EngineContext:
    """Measured world-state the evaluator reads but does not own:
    the gate shelf (Pack 003), the freeze flag (Pack 002)."""

    fetch_freeze: bool = False
    gate_lookup: Any = None  # Callable[[dict], dict | None] -> PASS entry


class PolicyEngine:
    def __init__(
        self,
        packs: list[Pack],
        receipts: GovernorReceipts | None = None,
        context: EngineContext | None = None,
        available: bool = True,
    ):
        self._packs = packs
        self._receipts = receipts
        self._context = context or EngineContext()
        self._available = available

    @classmethod
    def unavailable(cls, receipts: GovernorReceipts | None = None) -> PolicyEngine:
        """The engine-down engine (§8): gated classes fail closed,
        ungated classes proceed degraded. Used when pack loading
        itself failed, and by the acceptance tests."""
        return cls([], receipts=receipts, available=False)

    @property
    def packs(self) -> list[Pack]:
        return list(self._packs)

    def _mint(self, kind: str, fields: dict) -> str | None:
        if self._receipts is None:
            return None
        entry = self._receipts.mint(kind, fields)
        return entry.get("entry_hash")

    def _eval_descriptor(self, descriptor: dict) -> dict:
        """The descriptor plus derived, instrument-read fields the
        rules cite: gate state, freeze state, fetch domain math."""
        ev = dict(descriptor)
        ev["fetch_freeze"] = self._context.fetch_freeze
        ev["gate_pass"] = False
        if self._context.gate_lookup is not None:
            try:
                ev["gate_pass"] = self._context.gate_lookup(descriptor) is not None
            except Exception:  # noqa: BLE001 - a broken shelf reads as no PASS
                ev["gate_pass"] = False
        domains = ev.get("domains") or []
        granted = set(ev.get("granted_domains") or [])
        ev["domain_count"] = len(domains)
        ev["ungranted_count"] = len([d for d in domains if d not in granted])
        ev["has_ungranted"] = ev["ungranted_count"] > 0
        return ev

    def check(self, descriptor: dict) -> Verdict:
        act_class = descriptor.get("act_class", "")
        gated = act_class in GATED_CLASSES
        act_hash = _receipts.sha256_hex(_receipts.canonical(descriptor))
        if not self._available:
            if gated:
                rid = self._mint(
                    "policy-verdict",
                    {
                        "outcome": "engine-down-deny",
                        "act_class": act_class,
                        "act_hash": act_hash,
                    },
                )
                return Verdict(
                    action="deny",
                    receipt_ids=[r for r in [rid] if r],
                    gated=True,
                    detail="policy engine unavailable — gated class fails closed",
                )
            rid = self._mint(
                "policy-verdict",
                {
                    "outcome": "degraded",
                    "act_class": act_class,
                    "act_hash": act_hash,
                },
            )
            return Verdict(
                action="allow",
                receipt_ids=[r for r in [rid] if r],
                gated=False,
                degraded=True,
                detail="policy engine unavailable — ungated class proceeds degraded",
            )

        ev = self._eval_descriptor(descriptor)
        phase = ev.get("phase", "launch")
        candidates = [
            rule
            for pack in self._packs
            for rule in pack.rules
            if act_class in rule.act_classes
            and (rule.phase is None or rule.phase == phase)
        ]
        firing = [r for r in candidates if not r.default and matches(r.when, ev)]
        if not firing:
            defaults = [r for r in candidates if r.default]
            if defaults:
                return self._apply(defaults[0], descriptor, act_hash, gated)
            rid = self._mint(
                "policy-verdict",
                {
                    "outcome": "allow-no-rule",
                    "act_class": act_class,
                    "act_hash": act_hash,
                },
            )
            return Verdict(
                action="allow",
                receipt_ids=[r for r in [rid] if r],
                gated=gated,
                detail="no rule governs this act class",
            )

        top = max(r.priority for r in firing)
        winners = [r for r in firing if r.priority == top]
        actions = {r.action for r in winners}
        if len(actions) > 1:
            first, second = winners[0], winners[1]
            ids = []
            for rule in (first, second):
                rid = self._mint(
                    rule.receipt,
                    {
                        "rule": rule.id,
                        "outcome": "conflict",
                        "act_class": act_class,
                        "act_hash": act_hash,
                        "action": rule.action,
                    },
                )
                if rid:
                    ids.append(rid)
            return Verdict(
                action="stage:chairman-conflict",
                rule_ids=[first.id, second.id],
                receipt_ids=ids,
                gated=gated,
                conflict=(first.id, second.id),
                detail=(
                    f"rules {first.id} ({first.action}) and {second.id} "
                    f"({second.action}) contradict — staged for the Chairman"
                ),
            )
        return self._apply(winners[0], descriptor, act_hash, gated)

    def _apply(
        self, rule: Rule, descriptor: dict, act_hash: str, gated: bool
    ) -> Verdict:
        action = rule.action
        detail = rule.summary or f"{rule.id} fired"
        unmet: list[str] = []
        receipt_ids: list[str] = []

        if action.startswith("route:") and rule.pack == "compute-routing":
            if descriptor.get("lambda_available") is False:
                action = "queue:offbox"
                detail = (
                    f"{rule.id} routed off-box but Lambda is unavailable — "
                    "queued off-box (QUEUED-OFFBOX), never silently local"
                )
            else:
                context = descriptor.get("launch_context")
                if context is not None and context not in {
                    "persistent",
                    "daemonized",
                }:
                    unmet.append(
                        "launch context must be persistent or daemonized "
                        "(long-runner anchoring law, 2026-11-01)"
                    )
                if (
                    descriptor.get("checkpointed") is not None
                    and descriptor.get("checkpointed") is not True
                ):
                    unmet.append("routed jobs must be disk-checkpointed")
                if unmet:
                    action = "stage:routing-preconditions"
                    detail = f"{rule.id} route blocked on preconditions"

        override_by = None
        waiver = descriptor.get("chairman_waiver")
        if (
            waiver
            and rule.override == "chairman-by-name"
            and (action == "deny" or action.startswith("stage:"))
        ):
            override_by = str(waiver)
            detail = f"{rule.id} overridden by the Chairman, by name: {waiver}"
            action = "allow"

        fields: dict[str, Any] = {
            "rule": rule.id,
            "act_class": descriptor.get("act_class"),
            "act_hash": act_hash,
            "action": action,
            "outcome": "verdict",
        }
        if override_by:
            fields["override_by"] = override_by
        if unmet:
            fields["unmet_preconditions"] = unmet
        if rule.id == "COMPUTE.BURST-PARALLEL" and action.startswith("route:"):
            shards = int(descriptor.get("shard_count", 0))
            for shard in range(shards):
                rid = self._mint(
                    "routing", {**fields, "shard": shard, "outcome": "routing"}
                )
                if rid:
                    receipt_ids.append(rid)
            fields["per_shard_receipts"] = shards
        rid = self._mint(rule.receipt, fields)
        if rid:
            receipt_ids.append(rid)
        return Verdict(
            action=action,
            rule_ids=[rule.id],
            receipt_ids=receipt_ids,
            gated=gated,
            detail=detail,
            override_by=override_by,
            unmet_preconditions=unmet,
        )
