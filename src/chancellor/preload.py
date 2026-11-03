"""Preload Service — SPEC §4 (Chancellor, Governor of Operations).

A session should not have to re-derive the house's standing orders
from a 245 KB standing file. A preload is the short, versioned,
class-scoped brief a session receives for its kind of work: the
canons in force (from the Manifest), the pack rules that will judge
its acts, and the registry slice it may touch — locations and tiers,
never contents.

The size budget is a hard cap enforced at issuance (§8): a preload
that exceeds it does not issue. Its failure mints a drift-kind
finding and stages; a session never receives an over-budget brief
and never receives none silently.
"""

from __future__ import annotations

from datetime import UTC, datetime

from . import receipts as _receipts
from .governor_receipts import GovernorReceipts
from .manifest import Registry
from .packs import BUILTIN_PACKS
from .policy import load_pack

SIZE_BUDGET_BYTES = 4096

CLASSES = (
    "compute-heavy",
    "external-fetch",
    "submission",
    "outbound-send",
    "money",
    "build",
    "research",
    "household",
    "markets",
)

# Which packs judge which class's acts (§4). Classes not listed for
# any pack (build, research, household, markets) are canon-only in
# v1: the preload carries their canon and registry slice, and the
# engine's universal packs still judge gated acts.
CLASS_PACKS: dict[str, list[str]] = {
    "compute-heavy": ["compute-routing"],
    "external-fetch": ["fetch-preflight"],
    "submission": ["submission-gate"],
    "outbound-send": ["money-staging"],
    "money": ["money-staging"],
}


class PreloadBloatError(ValueError):
    """The class's canon set exceeds the issuance budget (§8)."""


def _pack_by_name() -> dict:
    return {raw["name"]: raw for raw in BUILTIN_PACKS}


def _rule_fingerprint(raw_pack: dict) -> str:
    slim = [
        {
            "id": r["id"],
            "action": r["action"],
            "when": r.get("when") or {},
            "founded_by": r["founded_by"],
        }
        for r in raw_pack["rules"]
    ]
    return _receipts.sha256_hex(
        _receipts.canonical({"pack": raw_pack["name"], "rules": slim})
    )


def _canon_for(registry: Registry, cls: str) -> list[dict]:
    """Canon entries in force for a class: entries tagged with the
    class, plus untagged canon, which is universal by definition."""
    out = []
    for entry in registry.entries:
        if entry["kind"] != "canon":
            continue
        classes = entry.get("classes")
        if classes is None or cls in classes:
            out.append(entry)
    return out


def _slice_for(registry: Registry, cls: str) -> list[dict]:
    return [e for e in registry.entries if cls in (e.get("classes") or [])]


def compute_stamp(registry: Registry, cls: str) -> str:
    packs = _pack_by_name()
    pack_part = [
        {
            "name": name,
            "version": packs[name]["version"],
            "rules": _rule_fingerprint(packs[name]),
        }
        for name in CLASS_PACKS.get(cls, [])
    ]
    canon_part = [
        {"name": e["name"], "content_hash": e.get("content_hash")}
        for e in _canon_for(registry, cls)
    ]
    digest = _receipts.sha256_hex(
        _receipts.canonical({"class": cls, "packs": pack_part, "canon": canon_part})
    )
    return f"pl-{cls}-{digest[:12]}"


def render(registry: Registry, cls: str, charge: str, stamp: str) -> str:
    packs = _pack_by_name()
    lines = [
        f"CHANCELLOR PRELOAD {stamp}",
        f"class: {cls}",
        f"charge: {charge}",
        f"frame: {_receipts.FRAME_HASH}",
        f"issued: {datetime.now(UTC).isoformat(timespec='seconds')}",
        "",
    ]
    for name in CLASS_PACKS.get(cls, []):
        raw = packs[name]
        pack = load_pack(raw)
        lines.append(f"PACK {name} v{raw['version']} — rules that judge this class:")
        for rule in pack.rules:
            lines.append(f"- {rule.id} [{rule.action}] {rule.summary}")
        lines.append("")
    canon = _canon_for(registry, cls)
    if canon:
        lines.append("CANON IN FORCE:")
        for entry in canon:
            text = entry.get("operative_text") or entry.get("purpose", "")
            lines.append(f"- {entry['name']}: {text}")
        lines.append("")
    slice_entries = _slice_for(registry, cls)
    if slice_entries:
        lines.append("REGISTRY SLICE (locations + tiers; contents stay home):")
        for entry in slice_entries:
            lines.append(
                f"- {entry['name']} [{entry['kind']}/{entry['tier']}] "
                f"{entry['canonical_location']}"
            )
        lines.append("")
    return "\n".join(lines)


def issue_preload(
    registry: Registry,
    receipts: GovernorReceipts | None,
    cls: str,
    charge: str,
) -> dict:
    """Issue (or re-issue) the class preload. Enforces the hard
    budget at issuance; stamps the version into the registry;
    receipts the issuance (§4, §5.1)."""
    if cls not in CLASSES:
        raise ValueError(f"unknown preload class: {cls!r} (one of {CLASSES})")
    stamp = compute_stamp(registry, cls)
    text = render(registry, cls, charge, stamp)
    size = len(text.encode("utf-8"))
    if size > SIZE_BUDGET_BYTES:
        if receipts is not None:
            receipts.mint(
                "drift",
                {
                    "artifact": f"preload-class:{cls}",
                    "expected": f"<= {SIZE_BUDGET_BYTES} bytes at issuance",
                    "found": f"{size} bytes",
                    "fix": (
                        "staged: the class canon set exceeds the preload "
                        "budget — split the class or shorten operative "
                        "texts in the registry"
                    ),
                },
            )
        raise PreloadBloatError(
            f"preload for class {cls} is {size} bytes, over the "
            f"{SIZE_BUDGET_BYTES}-byte budget — not issued"
        )
    versions = registry.meta["preload_versions"].setdefault(
        cls, {"current": None, "invalidated": []}
    )
    versions["current"] = stamp
    registry.save()
    if receipts is not None:
        receipts.mint(
            "preload-issued",
            {
                "artifact": f"preload-class:{cls}",
                "stamp": stamp,
                "class": cls,
                "charge": charge,
                "bytes": size,
            },
        )
    return {"stamp": stamp, "text": text, "bytes": size, "class": cls}
