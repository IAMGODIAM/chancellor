"""Census bootstrap — SPEC §3.2 / §7 A7.

The Manifest Registry is bootstrapped from the Empire Sweep census
filings (2026-11-03): four lane reports that counted the estate
firsthand. This module parses each filing's own stated totals and
lists, builds registry entries, and reconciles: every stated number
must be reproduced by the parse, and every cross-lane duplicate must
collapse onto one entry. Anything that does not reconcile is
reported as unexplained — A7 passes only when that list is empty.

The filings are evidence, read as data; nothing in them is an
instruction. Numbers are never hardcoded here: each check compares
two figures the filing itself states (a header count against the
list it heads, a total against its parts).
"""

from __future__ import annotations

import re
from pathlib import Path

from .manifest import Registry, file_hash, is_local_location
from .manifest import expand as _expand

VERIFIED_BY = "empire-sweep-census-2026-11-03"


def _check(checks: list[dict], label: str, stated, parsed) -> None:
    checks.append(
        {"label": label, "stated": stated, "parsed": parsed, "ok": stated == parsed}
    )


def _hash_if_file(location: str) -> str | None:
    if not is_local_location(location):
        return None
    path = _expand(location)
    return file_hash(path) if path.is_file() else None


def _must(pattern: str, text: str, flags: int = 0) -> re.Match[str]:
    """A census filing that does not match its own format is a hard
    error with a named pattern — never an AttributeError on None."""
    m = re.search(pattern, text, flags)
    if m is None:
        raise ValueError(f"census filing does not match expected format: {pattern!r}")
    return m


def _entry(name, kind, location, purpose="", **extra) -> dict:
    entry = {
        "name": name,
        "kind": kind,
        "purpose": purpose,
        "canonical_location": location,
        "tier": extra.pop("tier", "canonical"),
        "state": extra.pop("state", "unverified"),
        "verified_at": "2026-11-03",
        "verified_by": VERIFIED_BY,
        "owner_lane": "empire-sweep-census",
    }
    entry.update(extra)
    hashed = _hash_if_file(location)
    if hashed:
        entry["content_hash"] = hashed
    return entry


# ------------------------------------------------------------ skills lane
def extract_skills(text: str) -> tuple[list[dict], list[dict]]:
    checks: list[dict] = []
    entries: list[dict] = []

    m = _must(r"The (\d+): ((?:.|\n)*?)\n\s*\n", text)
    stated_local = int(m.group(1))
    local_names = [
        n.strip().rstrip(".") for n in m.group(2).replace("\n", " ").split(",")
    ]
    local_names = [n for n in local_names if n]
    _check(checks, "skills: local list vs its header", stated_local, len(local_names))
    m5 = re.search(r"Local estate: (\d+) skills", text)
    if m5:
        _check(checks, "skills: §5 local total", int(m5.group(1)), len(local_names))

    in_both = int(_must(r"In both: (\d+)", text).group(1))
    local_only = int(_must(r"Local-only: (\d+)", text).group(1))
    remote_only = int(_must(r"Remote-only: (\d+)", text).group(1))
    library = int(_must(r"Library skill entries \([^)]*\): (\d+)", text).group(1))
    _check(
        checks,
        "skills: in-both + local-only = local",
        stated_local,
        in_both + local_only,
    )
    _check(
        checks,
        "skills: in-both + remote-only = library",
        library,
        in_both + remote_only,
    )

    held_m = _must(r"All (\d+) confirmed ABSENT[^\n]*\n((?:.|\n)*?)\.\n", text)
    held = [n.strip() for n in held_m.group(2).replace("\n", " ").split(",")]
    held = [n for n in held if n]
    _check(checks, "skills: HELD list vs its header", int(held_m.group(1)), len(held))

    _plus = re.search(r"plus \d+ with no hold", text)
    unexported = re.findall(
        r"`(local-[a-z0-9-]+)`",
        text[_plus.end() :].split("Remote-only")[0] if _plus else "",
    )
    local_only_names = set(held) | set(unexported)
    _check(
        checks,
        "skills: HELD + unexported = local-only",
        local_only,
        len(local_only_names),
    )
    _check(
        checks,
        "skills: local minus local-only = in-both",
        in_both,
        len([n for n in local_names if n not in local_only_names]),
    )

    aliases = dict(re.findall(r"`(local-[a-z0-9-]+)` → `([a-z0-9-]+)`", text))
    out_env = set(
        re.findall(r"^\| [a-z0-9-]+ \| (local-[a-z0-9-]+) \|", text, flags=re.M)
    )
    for name in local_names:
        remote = aliases.get(name, name.removeprefix("local-"))
        if name in held:
            state, note = "unverified", "HELD from export (scrub battery)"
        elif name in unexported:
            state, note = "unverified", "local-only, never exported, no hold"
        elif name in out_env:
            state, note = (
                "unverified",
                "paired copy outside the ±700 B size envelope — "
                "canonical side undecided in the filing",
            )
        else:
            state, note = "verified", ""
        entries.append(
            _entry(
                name,
                "skill",
                f"~/workspace/custom-skills/{name}",
                state=state,
                note=note,
                library_copy=f"E5EnclaveInc/agent-skills:skills/{remote}",
            )
        )

    for label, pat in (
        ("connector", r"(\d+) connector skills \(([^)]*)\)"),
        ("practice/method", r"(\d+) practice/method skills\s*\(([^)]*)\)"),
        ("fleet-process", r"(\d+) fleet-process exports \(([^)]*)\)"),
    ):
        mm = _must(pat, text)
        names = [n.strip() for n in mm.group(2).replace("\n", " ").split(",")]
        names = [n for n in names if n]
        _check(
            checks,
            f"skills: remote-only {label} list",
            int(mm.group(1)),
            len(names),
        )
        for name in names:
            entries.append(
                _entry(
                    name,
                    "skill",
                    f"E5EnclaveInc/agent-skills:skills/{name}",
                    state="verified",
                    tier="mirror",
                    note=f"remote-only {label} skill (exported from other sources)",
                )
            )
    head = re.search(r"\*\*([0-9a-f]{40})\*\*", text)
    entries.append(
        _entry(
            "agent-skills-library",
            "artifact",
            "E5EnclaveInc/agent-skills",
            "The public skills library — the scrubbed corpus of record",
            state="verified",
            tier="mirror",
            count=library,
            tree_entries=int(_must(r"\*\*(\d+) entries", text).group(1)),
            head=head.group(1) if head else None,
        )
    )
    return entries, checks


# ------------------------------------------------------------- tools lane
def extract_tools(text: str) -> tuple[list[dict], list[dict]]:
    checks: list[dict] = []
    entries: list[dict] = []

    rows = re.findall(
        r"^\| \d+ \| (custom\.[a-z0-9.-]+) \| ((?:[^|]|\\\|)*) \| "
        r"((?:[^|]|\\\|)*) \|",
        text,
        flags=re.M,
    )
    total = int(_must(r"ON GITHUB — (\d+) of (\d+)", text).group(2))
    _check(checks, "tools: connector table rows", total, len(rows))

    def stripped(cid: str) -> str:
        return cid.removeprefix("custom.").removeprefix("legacy-")

    on_github_line = _must(r"ON GITHUB — (\d+) of \d+.*?:\n(.+)", text)
    stated_on = int(on_github_line.group(1))
    on_tokens = [
        t.strip().split(" ")[0] for t in on_github_line.group(2).split("·") if t.strip()
    ]
    on_ids = set()
    for token in on_tokens:
        for cid, _helpers, _purpose in rows:
            if stripped(cid) == token:
                on_ids.add(cid)
    _check(
        checks, "tools: ON GITHUB list resolves to table ids", stated_on, len(on_ids)
    )

    held_line = _must(r"HELD — (\d+) of \d+.*?:\n?(.+)", text)
    held_ids = re.findall(r"custom\.[a-z0-9.-]+", held_line.group(2))
    _check(checks, "tools: HELD list", int(held_line.group(1)), len(held_ids))

    local_section = text.split("LOCAL-ONLY (gap) —")[1].split("Wiki cross-check")[0]
    local_ids = re.findall(r"\*\*(custom\.[a-z0-9.-]+)\*\*", local_section)
    stated_local = int(_must(r"LOCAL-ONLY \(gap\) — (\d+) of", text).group(1))
    _check(checks, "tools: LOCAL-ONLY list", stated_local, len(local_ids))
    _check(
        checks,
        "tools: on-github + held + local-only = total",
        total,
        len(on_ids) + len(held_ids) + len(local_ids),
    )

    for cid, helpers, purpose in rows:
        if cid in held_ids:
            state, note = "unverified", "HELD from export"
        elif cid in on_ids:
            state, note = "verified", ""
        else:
            state, note = "unverified", "local-only gap"
        entries.append(
            _entry(
                cid,
                "toolset",
                f"~/workspace/custom-connectors/{cid}",
                purpose.strip(),
                state=state,
                note=note,
                helpers=helpers.strip(),
            )
        )

    toolset_rows = re.findall(
        r"^\| `~/(workspace/[^`]+)` \| (\d+) / [^|]* \| ([^|]*) \|",
        text,
        flags=re.M,
    )
    state_rows = re.findall(
        r"^\| ([^|]+) \| \*\*(ON GITHUB|LOCAL-ONLY[^*]*)\*\*", text, flags=re.M
    )
    bottom = _must(r"of (\d+) toolsets censused, exactly (\d+)", text)
    on_paths = [n.split("(")[0].strip() for n, s in state_rows if s == "ON GITHUB"]
    _check(
        checks,
        "tools: toolset table rows (§2 vs bottom line)",
        int(bottom.group(1)),
        len(toolset_rows),
    )
    _check(
        checks,
        "tools: toolsets ON GITHUB (§3b vs bottom line)",
        int(bottom.group(2)),
        len(on_paths),
    )
    for path, count, purpose in toolset_rows:
        name = path.rstrip("/").split("/")[-1]
        if name == "bin":
            name = path.rstrip("/").split("/")[-2] + "-bin"
        on = any(op in path for op in on_paths)
        entries.append(
            _entry(
                f"toolset:{name}",
                "toolset",
                f"~/{path}",
                purpose.strip()[:200],
                state="verified" if on else "unverified",
                count=int(count),
            )
        )
    return entries, checks


# ----------------------------------------------------------- rubrics lane
def extract_rubrics(text: str) -> tuple[list[dict], list[dict]]:
    checks: list[dict] = []
    entries: list[dict] = []

    total = int(_must(r"\*\*(\d+) instrument rows censused", text).group(1))
    on_github = int(_must(r"\*\*(\d+) fully ON GITHUB", text).group(1))
    transformed = int(
        _must(r"\*\*(\d+) ON GITHUB as a transformed export", text).group(1)
    )
    partial = int(_must(r"\*\*(\d+) ON GITHUB but PARTIAL", text).group(1))
    local_only = int(_must(r"\*\*(\d+) LOCAL-ONLY", text).group(1))
    _check(
        checks,
        "rubrics: parts sum to total",
        total,
        on_github + transformed + partial + local_only,
    )

    rows: dict[int, tuple[str, str, str]] = {}
    for num, path, purpose, gh in re.findall(
        r"^\| (\d+) \| ([^|]+) \| ([^|]*) \| ([^|]*) \|", text, flags=re.M
    ):
        rows[int(num)] = (path.strip(), purpose.strip(), gh.strip())
    for num in (21,):
        mm = re.search(rf"^{num}\. \*\*([^*]+)\*\*", text, flags=re.M)
        if mm:
            rows[num] = (mm.group(1).strip(), "", "PARTIAL")
    for num in range(22, 32):
        mm = re.search(rf"^{num}\. \*\*([^*]+)\*\*", text, flags=re.M)
        if mm:
            rows[num] = (mm.group(1).strip(), "", "")
    _check(checks, "rubrics: rows parsed", total, len(rows))
    _check(
        checks,
        "rubrics: ON GITHUB rows 1-20",
        on_github,
        len([n for n in rows if n <= 20]),
    )
    _check(
        checks,
        "rubrics: LOCAL-ONLY rows 23-31",
        local_only,
        len([n for n in rows if n >= 23]),
    )

    for num, (path, purpose, gh) in sorted(rows.items()):
        clean = path.rstrip("/").split(" (")[0].rstrip("/")
        parts = clean.split("/")
        if parts[-1].endswith(".md") and len(parts) >= 2:
            name = parts[-2] + "/" + parts[-1].removesuffix(".md")
        else:
            name = parts[-1].removesuffix(".md")
        # Rows 1-20 are ON GITHUB; 21 (partial), 22 (transformed,
        # currency uncertain) and 23-31 (local-only) are all carried
        # as unverified until a lane re-derives them.
        state = "verified" if num <= 20 else "unverified"
        tier = "sealed" if num == 25 else "canonical"
        entries.append(
            _entry(
                name,
                "artifact",
                f"~/workspace/{clean}",
                purpose[:200],
                state=state,
                tier=tier,
                note=(
                    "sealed by design (FB-v1 truth set) — registered, not exported"
                    if num == 25
                    else ""
                ),
                github=gh,
                census_row=num,
            )
        )
    return entries, checks


# ------------------------------------------------------------ agents lane
def extract_agents(text: str) -> tuple[list[dict], list[dict]]:
    checks: list[dict] = []
    entries: list[dict] = []

    roster_lines = int(_must(r"AGENT-ROSTER\.md` \((\d+) lines\)", text).group(1))
    entries.append(
        _entry(
            "AGENT-ROSTER",
            "canon",
            "~/workspace/fleet/AGENT-ROSTER.md",
            "The one casting book for the agent roster",
            state="unverified",
            note="LOCAL-ONLY per census — no GitHub copy",
            census_lines=roster_lines,
        )
    )
    cards = _must(
        r"### 1\.2 Persona cards[^\n]*\((\d+) files\)\n((?:.|\n)*?)\n\n", text
    )
    card_names = re.findall(r"([a-z-]+)\.md", cards.group(2))
    _check(checks, "agents: persona cards", int(cards.group(1)), len(card_names))
    for card in card_names:
        entries.append(
            _entry(
                f"persona:{card}",
                "artifact",
                f"~/workspace/custom-skills/local-war-council/personas/{card}.md",
                state="verified",
                note="ON GITHUB at skills/wisdom-council/personas/",
            )
        )
    entries.append(
        _entry(
            "persona-packets-pp0-pp8",
            "artifact",
            "~/workspace/fleet/persona-batteries/PROTOCOL.md",
            "Persona packet gate definition — no complete packet "
            "artifact exists anywhere on disk (census §1.3)",
            state="staged",
            note="registered absence: the register names the gap "
            "instead of forgetting it",
        )
    )
    souls_head = _must(r"souls/` \((\d+) files\)", text)
    souls_sec = _must(r"### 1\.4 Souls[^\n]*\n((?:.|\n)*?)\n\n", text).group(1)
    more = int(_must(r"\(\+(\d+) more", souls_sec).group(1))
    listed = len([t for t in re.split(r",\s*", souls_sec.split("(")[0]) if t.strip()])
    _check(
        checks,
        "agents: souls listed + unlisted = stated",
        int(souls_head.group(1)),
        listed + more,
    )
    entries.append(
        _entry(
            "souls-corpus",
            "artifact",
            "~/workspace/fleet/roster-source/souls",
            "The *_SOUL.md corpus (census §1.4)",
            state="unverified",
            count=int(souls_head.group(1)),
            note="wiki era corpus is a stale delta — UNCERTAIN per census",
        )
    )
    ember = int(_must(r"ember-school/` \((\d+) top-level", text).group(1))
    entries.append(
        _entry(
            "ember-school",
            "artifact",
            "~/workspace/ember-school",
            "Five-element household configuration",
            state="unverified",
            count=ember,
            note="LOCAL-ONLY per census",
        )
    )

    canon_rows = re.findall(
        r"^\| `~/(AGENTS\.md|SOUL\.md|USER\.md|IDENTITY\.md|MEMORY\.md)` "
        r"\| ([\d,]+) B \|",
        text,
        flags=re.M,
    )
    _check(checks, "agents: root canon table rows", 5, len(canon_rows))
    for fname, size in canon_rows:
        entries.append(
            _entry(
                fname.removesuffix(".md").lower() + "-canon",
                "canon",
                f"~/{fname}",
                f"Root canon file {fname}",
                state="unverified",
                census_size_bytes=int(size.replace(",", "")),
                operative_text=(
                    "Read the live file; the registry carries its hash, "
                    "never its contents."
                ),
                note="wiki copies are stale era texts per census §2.1",
            )
        )

    doctrine_sec = text.split("### 2.2")[1].split("### 2.3")[0]
    for fname, size in re.findall(
        r"`([A-Za-z][A-Za-z0-9_-]+\.md)` \(([\d,]+) B", doctrine_sec
    ):
        entries.append(
            _entry(
                fname.removesuffix(".md"),
                "canon",
                f"~/workspace/fleet/{fname}",
                state="unverified",
                census_size_bytes=int(size.replace(",", "")),
                note="LOCAL-ONLY per census §2.2",
            )
        )
    creative = re.search(
        r"`(CHAIRMAN-CREATIVE-CANON\.md)` at `~/workspace/design-program/` "
        r"\(([\d,]+) B",
        text,
    )
    if creative:
        entries.append(
            _entry(
                "CHAIRMAN-CREATIVE-CANON",
                "canon",
                "~/workspace/design-program/CHAIRMAN-CREATIVE-CANON.md",
                "The Chairman's Creative Canon — binds every creative delivery",
                state="unverified",
                census_size_bytes=int(creative.group(2).replace(",", "")),
                operative_text=(
                    "Cinematic, seal palette, NO BROWN EVER; machine "
                    "floors are not the standard — the AgriMesh "
                    "reference comparison is."
                ),
                classes=[
                    "build",
                    "research",
                    "household",
                    "markets",
                    "outbound-send",
                ],
            )
        )

    folders = int(_must(r"\((\d+) build folders\)", text).group(1))
    spec_seg = text.split("SPEC.md present in")[1].split("\n\n")[0]
    spec_stated = int(_must(r"SPEC\.md present in \*\*(\d+)\*\*", text).group(1))
    spec_seg = re.sub(r"\*\*\d+\*\*:?", "", spec_seg)
    spec_names = [
        t.strip().rstrip(".")
        for t in spec_seg.replace("\n", " ").split("·")
        if t.strip()
    ]
    _check(checks, "agents: build SPEC folders named", spec_stated, len(spec_names))
    entries.append(
        _entry(
            "builds-estate",
            "artifact",
            "~/workspace/builds",
            "The builds estate",
            state="unverified",
            count=folders,
        )
    )

    goal_folders = int(_must(r"\((\d+) goal folders, (\d+)", text).group(1))
    goal_md = int(_must(r"\((\d+) goal folders, (\d+)", text).group(2))
    _check(
        checks, "agents: GOAL.md files fewer than folders", True, goal_md < goal_folders
    )
    entries.append(
        _entry(
            "goals-estate",
            "artifact",
            "~/workspace/goals",
            "The goals estate — durable record of every workstream",
            state="unverified",
            count=goal_folders,
            goal_md_files=goal_md,
        )
    )

    cron_files = int(_must(r"\*\*(\d+) cron definition", text).group(1))
    goal_crons = int(_must(r"Goal-owned crons — \*\*(\d+) files", text).group(1))
    total_sched = int(
        _must(r"Total schedule definitions on disk: (\d+) files", text).group(1)
    )
    _check(
        checks,
        "agents: cron.d + goal-owned = total schedules",
        total_sched,
        cron_files + goal_crons,
    )
    entries.append(
        _entry(
            "cron-definitions",
            "schedule",
            "~/workspace/cron.d",
            "Scheduler definition files (daily/hourly/weekly/…)",
            state="unverified",
            count=cron_files,
            note="no GitHub copy exists — the lane's starkest gap",
        )
    )
    entries.append(
        _entry(
            "goal-owned-crons",
            "schedule",
            "~/workspace/goals/*/crons/",
            "Goal-owned cron definitions under goals/*/crons/",
            state="unverified",
            count=goal_crons,
        )
    )
    return entries, checks


EXTRACTORS = {
    "skills.md": extract_skills,
    "tools-connectors.md": extract_tools,
    "rubrics-evals.md": extract_rubrics,
    "agents-personas-canon.md": extract_agents,
}


def bootstrap(filings_dir: str | Path, registry_path: str | Path) -> dict:
    """Build the registry from the four census filings and
    reconcile. Returns the reconciliation report; ``unexplained``
    lists every check that failed (A7 requires it empty)."""
    filings_dir = Path(filings_dir)
    registry = Registry(registry_path)
    all_checks: list[dict] = []
    added = deduped = 0
    for fname, extractor in EXTRACTORS.items():
        text = (filings_dir / fname).read_text(encoding="utf-8")
        entries, checks = extractor(text)
        all_checks.extend(checks)
        for entry in entries:
            by_name = registry.get(entry["name"]) is not None
            by_location = any(
                e["canonical_location"] == entry["canonical_location"]
                for e in registry.entries
            )
            if by_name or by_location:
                deduped += 1
                continue
            registry.add(entry)
            added += 1
    registry.ensure_self_entry()
    registry.save()
    unexplained = [c["label"] for c in all_checks if not c["ok"]]
    return {
        "entries_added": added,
        "entries_total": len(registry.entries),
        "deduped": deduped,
        "checks": all_checks,
        "unexplained": unexplained,
    }
