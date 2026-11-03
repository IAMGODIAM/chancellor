"""Manifest Registry — SPEC §3 (Chancellor, Governor of Operations).

One register of everything the fleet owns: for each item, where the
canonical copy lives, what tier it sits in, which copy is the truth,
and when it was last verified against reality. Bootstrapped from the
Empire Sweep census (2026-11-03); from then on maintained by the
receipts and the verifier, never by memory.

The store is a JSON file in v1 — the register is data, and its own
copy inside it is an entry like any other (§3.3), so the register
can drift-check itself.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .governor_receipts import GovernorReceipts

KINDS = ("canon", "skill", "toolset", "schedule", "artifact", "contract")
TIERS = ("canonical", "mirror", "sealed", "excluded-with-reason")
STATES = ("verified", "corrected", "unverified", "staged")

VERIFIED_BY = "chancellor:manifest-verify"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def file_hash(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def is_local_location(location: str) -> bool:
    """Locations are local paths (~/ or /) or ``repo:path`` remotes.
    Only local single files are hash-verifiable in v1; directories
    and remotes are carried as census facts and skipped."""
    return location.startswith(("/", "~/"))


def expand(location: str) -> Path:
    return Path(location).expanduser()


class Registry:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.exists():
            self._doc = json.loads(self.path.read_text(encoding="utf-8"))
        else:
            self._doc = {
                "schema": "chancellor-manifest-1",
                "meta": {
                    "created_at": _now(),
                    "fetch_freeze": False,
                    "preload_versions": {},
                },
                "entries": [],
            }
        self._doc.setdefault("meta", {}).setdefault("preload_versions", {})

    # ------------------------------------------------- persistence
    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(self._doc, indent=1, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    # ----------------------------------------------------- entries
    @property
    def entries(self) -> list[dict]:
        return self._doc["entries"]

    @property
    def meta(self) -> dict:
        return self._doc["meta"]

    def get(self, name: str) -> dict | None:
        for entry in self._doc["entries"]:
            if entry["name"] == name:
                return entry
        return None

    def add(self, entry: dict, receipts: GovernorReceipts | None = None) -> dict:
        """Register (or re-register) an entry. Re-registering a canon
        entry under a changed hash invalidates that class's current
        preload stamp — a preload serves the canon it was minted
        from, or it serves nothing (§4)."""
        entry = self._normalize(entry)
        existing = self.get(entry["name"])
        if existing is not None:
            if existing.get("kind") == "canon" and existing.get(
                "content_hash"
            ) != entry.get("content_hash"):
                classes = existing.get("classes")
                if not classes:
                    # Untagged canon is universal: it is in force for
                    # every class, so every outstanding stamp falls.
                    classes = [
                        cls
                        for cls, v in self.meta["preload_versions"].items()
                        if v.get("current")
                    ]
                for cls in classes:
                    self._invalidate_preload(cls, receipts=receipts)
            self._doc["entries"][self._doc["entries"].index(existing)] = entry
        else:
            self._doc["entries"].append(entry)
        return entry

    def _normalize(self, entry: dict) -> dict:
        for key in ("name", "kind", "canonical_location"):
            if not entry.get(key):
                raise ValueError(f"manifest entry missing {key}: {entry!r}")
        if entry["kind"] not in KINDS:
            raise ValueError(f"unknown manifest kind: {entry['kind']}")
        tier = entry.get("tier", "canonical")
        if tier not in TIERS:
            raise ValueError(f"unknown manifest tier: {tier}")
        out = dict(entry)
        out.setdefault("tier", "canonical")
        out.setdefault("state", "unverified")
        if out["state"] not in STATES:
            raise ValueError(f"unknown manifest state: {out['state']}")
        return out

    def _invalidate_preload(
        self, cls: str, receipts: GovernorReceipts | None = None
    ) -> str | None:
        versions = self.meta["preload_versions"].setdefault(
            cls, {"current": None, "invalidated": []}
        )
        current = versions.get("current")
        if current:
            versions["invalidated"].append(current)
            versions["current"] = None
            if receipts is not None:
                receipts.mint(
                    "drift",
                    {
                        "artifact": f"preload-class:{cls}",
                        "expected": "canon unchanged since preload issuance",
                        "found": f"canon entry changed; stamp {current} invalidated",
                        "fix": "reissue the class preload",
                    },
                )
            return current
        return None

    # ------------------------------------------------- verification
    def verify(
        self,
        slice_kind: str | None = None,
        receipts: GovernorReceipts | None = None,
    ) -> dict:
        """Re-derive a slice against the local tree (§3.3): hash
        every verifiable local entry, mint a drift finding per
        discrepancy, and apply the fix the entry's shape affords:

        - mirror copy drifted → the canonical copy is pushed over
          it; the receipt names expected vs found (§7 A2);
        - canonical entry drifted → the registry's recorded hash was
          wrong about reality; the registry corrects its own state
          and the receipt names expected vs found;
        - canonical file missing → the finding stages (state
          ``staged``) naming the decision it waits for; nothing is
          silently dropped.
        """
        findings: list[dict] = []
        checked = skipped = 0
        for entry in self.entries:
            if slice_kind and entry["kind"] != slice_kind:
                continue
            loc = entry["canonical_location"]
            mirror_of = entry.get("mirror_of")
            if (
                not is_local_location(loc)
                or "*" in loc
                or (mirror_of and not is_local_location(mirror_of))
            ):
                skipped += 1
                continue
            path = expand(loc)
            if path.is_dir():
                skipped += 1
                continue
            checked += 1
            if mirror_of:
                canonical = expand(mirror_of)
                expected = file_hash(canonical) if canonical.exists() else None
            else:
                expected = entry.get("content_hash")
            found = file_hash(path) if path.exists() else None
            if expected is not None and found == expected:
                entry["state"] = "verified"
                entry["verified_at"] = _now()
                entry["verified_by"] = VERIFIED_BY
                continue
            if found is None and mirror_of is None:
                entry["state"] = "staged"
                finding = {
                    "artifact": entry["name"],
                    "expected": expected,
                    "found": "missing",
                    "fix": (
                        "staged: canonical file absent at "
                        f"{loc} — restore it or retire the entry by name"
                    ),
                }
            elif mirror_of is not None and expected is not None:
                if path.exists():
                    shutil.copyfile(expand(mirror_of), path)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(expand(mirror_of), path)
                entry["content_hash"] = expected
                entry["state"] = "corrected"
                entry["verified_at"] = _now()
                entry["verified_by"] = VERIFIED_BY
                finding = {
                    "artifact": entry["name"],
                    "expected": expected,
                    "found": found,
                    "fix": f"canonical copy pushed from {mirror_of} to {loc}",
                }
            else:
                entry["content_hash"] = found
                entry["state"] = "corrected"
                entry["verified_at"] = _now()
                entry["verified_by"] = VERIFIED_BY
                finding = {
                    "artifact": entry["name"],
                    "expected": expected,
                    "found": found,
                    "fix": "registry state corrected to the found hash",
                }
            findings.append(finding)
            if receipts is not None:
                receipts.mint("drift", finding)
        self.save()
        return {"checked": checked, "skipped": skipped, "findings": findings}

    # --------------------------------------------------- self-entry
    def ensure_self_entry(self) -> dict:
        """The register registers itself (§3.3): its own row carries
        its hash, so a later verify catches the register drifting
        from its own record."""
        entry = self.get("manifest-registry")
        if entry is None:
            entry = {
                "name": "manifest-registry",
                "kind": "artifact",
                "purpose": (
                    "The Manifest Registry itself — the register of "
                    "everything the fleet owns (SPEC §3)"
                ),
                "canonical_location": str(self.path),
                "tier": "canonical",
                "state": "unverified",
                "owner_lane": "chancellor-governor",
            }
            self.add(entry)
        if self.path.exists():
            entry["content_hash"] = file_hash(self.path)
        return entry
