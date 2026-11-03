#!/usr/bin/env python3
"""Chancellor release-sync machinery: single source of truth, the
fail-closed release gate, and the surfaces manifest reader.

Design of record: the release-sync SPEC (Layers 1-2). Principles:
derive, don't copy; fail closed at the point of no return; the record
is not a surface; one engine, two callers (this script locally and in
CI, identically).

Subcommands:
  render   regenerate every derived surface from the declaration
  check    verify-only mode (the gate); --offline / --gate-a / --gate-b
  count    run the suite and print the passing count (JUnit formula)
  notes    print the CHANGELOG head entry's prose (for release bodies)

Stdlib only; Python >= 3.11. Exit codes: 0 = pass / done,
1 = a check failed, 2 = the tool itself could not run (render only;
`check` never exits 2 -- its blindness is reported as FAIL lines).
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import tomllib
import venv
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SCAN_PATTERN = r"(?<![0-9A-Za-z_.])v?[0-9]+\.[0-9]+\.[0-9]+\b"
VERSION_RE = re.compile(SCAN_PATTERN)
MARKER_RE = re.compile(
    r"<!-- release-sync:(?P<name>[A-Z0-9-]+) -->\n(?P<body>.*?)\n"
    r"<!-- /release-sync:(?P=name) -->",
    re.DOTALL,
)
CHANGELOG_HEAD_RE = re.compile(
    r"^## \[(?P<version>[0-9]+\.[0-9]+\.[0-9]+)\] "
    r"— (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})\s*$",
    re.MULTILINE,
)
MONTHS = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
]
SKIP_DIRS = {".git", "dist", "build", "__pycache__", ".venv", "node_modules"}
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".ico",
    ".pdf",
    ".zip",
    ".gz",
    ".whl",
    ".tar",
    ".bz2",
    ".xz",
}


class SurfaceError(Exception):
    """A managed surface could not be read, parsed, or rendered."""


# --------------------------------------------------------------------------
# Reading the tree's facts
# --------------------------------------------------------------------------


def load_manifest(root: Path) -> dict:
    path = root / "tools" / "release_surfaces.toml"
    if not path.is_file():
        raise SurfaceError("tools/release_surfaces.toml is missing")
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SurfaceError(f"manifest unreadable: {exc}") from exc


def declaration(root: Path) -> str:
    path = root / "pyproject.toml"
    try:
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        return str(data["project"]["version"])
    except (OSError, tomllib.TOMLDecodeError, KeyError) as exc:
        raise SurfaceError(f"pyproject declaration unreadable: {exc}") from exc


def changelog_head(root: Path) -> tuple[str, str]:
    path = root / "CHANGELOG.md"
    if not path.is_file():
        raise SurfaceError("CHANGELOG.md is missing")
    m = CHANGELOG_HEAD_RE.search(path.read_text(encoding="utf-8"))
    if not m:
        raise SurfaceError("CHANGELOG.md has no parseable head entry")
    return m.group("version"), m.group("date")


def citation_fields(root: Path) -> tuple[str | None, str | None]:
    path = root / "CITATION.cff"
    if not path.is_file():
        return None, None
    version = date = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("version:"):
            version = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("date-released:"):
            date = line.split(":", 1)[1].strip()
    return version, date


def claimed_count(root: Path) -> int | None:
    """The count the living surfaces currently claim (README tests line)."""
    path = root / "README.md"
    if not path.is_file():
        return None
    m = re.search(r"\*\*Tests:\*\* ([0-9]+) passing", path.read_text(encoding="utf-8"))
    return int(m.group(1)) if m else None


def release_date(root: Path) -> str:
    """ISO date for the status line: changelog head, else CITATION."""
    try:
        return changelog_head(root)[1]
    except SurfaceError:
        _, date = citation_fields(root)
        if date:
            return date
        raise SurfaceError("no release date source (CHANGELOG/CITATION)") from None


def format_status_date(iso: str) -> str:
    year, month, day = (int(p) for p in iso.split("-"))
    return f"{MONTHS[month - 1]} {day}, {year}"


# --------------------------------------------------------------------------
# Test count (SPEC 2.3): computed from a green run's JUnit XML, never typed
# --------------------------------------------------------------------------


def count_from_junit(xml_path: Path) -> int:
    tree = ET.parse(xml_path)
    root = tree.getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = sum(int(s.get("tests", 0)) for s in suites)
    failures = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    return tests - failures - errors - skipped


def run_suite(root: Path, junit_path: Path) -> tuple[int, int]:
    """Run the full suite on `root`; return (exit_code, passing_count)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", f"--junitxml={junit_path}"],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=1800,
    )
    if not junit_path.is_file():
        raise SurfaceError(f"suite produced no JUnit XML (exit {proc.returncode})")
    return proc.returncode, count_from_junit(junit_path)


# --------------------------------------------------------------------------
# Rendering (Layer 1)
# --------------------------------------------------------------------------


def _sub(pattern: str, repl: str, text: str, where: str) -> str:
    out, n = re.subn(pattern, repl, text, count=1)
    if n == 0:
        raise SurfaceError(f"{where}: expected pattern not found: {pattern}")
    return out


def render_region(name: str, body: str, version: str, count: int, date_iso: str) -> str:
    if name == "STATUS-LINE":
        prefix = f"**Status — {format_status_date(date_iso)}:** v{version}."
        return _sub(
            r"\*\*Status — [^*]+:\*\* v[0-9]+\.[0-9]+\.[0-9]+\.", prefix, body, name
        )
    if name == "TESTS-LINE":
        return _sub(
            r"\*\*Tests:\*\* [0-9]+ passing", f"**Tests:** {count} passing", body, name
        )
    if name == "TESTS-BADGE-ALT":
        return _sub(
            r'alt="Tests: [0-9]+ passing — gates green"',
            f'alt="Tests: {count} passing — gates green"',
            body,
            name,
        )
    if name == "RELEASE-BADGE":
        body = _sub(
            r"releases/tag/v[0-9]+\.[0-9]+\.[0-9]+",
            f"releases/tag/v{version}",
            body,
            name,
        )
        return _sub(
            r'alt="Release: v[0-9]+\.[0-9]+\.[0-9]+"',
            f'alt="Release: v{version}"',
            body,
            name,
        )
    if name == "WHATSNEW-HEADING":
        return _sub(
            r"## What's new in [0-9]+\.[0-9]+\.[0-9]+",
            f"## What's new in {version}",
            body,
            name,
        )
    raise SurfaceError(f"unknown marker region: {name}")


def render_readme(text: str, version: str, count: int, date_iso: str) -> str:
    seen: set[str] = set()

    def repl(m: re.Match) -> str:
        name = m.group("name")
        seen.add(name)
        body = render_region(name, m.group("body"), version, count, date_iso)
        return f"<!-- release-sync:{name} -->\n{body}\n<!-- /release-sync:{name} -->"

    out = MARKER_RE.sub(repl, text)
    expected = {
        "STATUS-LINE",
        "RELEASE-BADGE",
        "TESTS-BADGE-ALT",
        "TESTS-LINE",
        "WHATSNEW-HEADING",
    }
    missing = expected - seen
    if missing:
        raise SurfaceError(f"README marker regions missing: {sorted(missing)}")
    return out


def charwidths(template: str) -> dict[str, int]:
    m = re.search(r"^\s*CW:\s*(.+)$", template, re.MULTILINE)
    if not m:
        raise SurfaceError("badge template carries no CW: width table")
    table: dict[str, int] = {}
    for token in m.group(1).split():
        key, _, val = token.partition("=")
        table[" " if key == "SP" else key] = int(val)
    return table


def text_width_px(text: str, table: dict[str, int]) -> int:
    units = sum(table.get(ch, table.get("?", 556)) for ch in text)
    return round(units * 11 / 1000)


def fmt_coord(x: float) -> str:
    return f"{x:.1f}"


def render_badge(template: str, label: str, value: str, value_alt: str = "") -> str:
    table = charwidths(template)
    label_tl = text_width_px(label, table)
    value_tl = text_width_px(value, table)
    label_seg = label_tl + 12
    value_seg = value_tl + 12
    out = template
    for token, val in {
        "{WIDTH}": str(label_seg + value_seg),
        "{LABEL_SEG}": str(label_seg),
        "{VALUE_SEG}": str(value_seg),
        "{LABEL_X}": fmt_coord(label_seg / 2),
        "{VALUE_X}": fmt_coord(label_seg + value_seg / 2),
        "{LABEL_TL}": str(label_tl),
        "{VALUE_TL}": str(value_tl),
        "{LABEL}": label,
        "{VALUE}": value,
        "{VALUE_ALT}": value_alt or value,
    }.items():
        out = out.replace(token, val)
    # The template's comment header (incl. the CW table) is documentation
    # for humans; the generated badge is the bare SVG.
    return re.sub(r"<!--.*?-->\s*", "", out, flags=re.DOTALL)


def render_surfaces(root: Path, count: int) -> dict[str, str]:
    """path -> rendered content for every generated/marker surface."""
    version = declaration(root)
    date_iso = release_date(root)
    tools = root / "tools" / "templates"
    readme = (root / "README.md").read_text(encoding="utf-8")
    citation_tmpl = (tools / "CITATION.cff.tmpl").read_text(encoding="utf-8")
    badge_rel_tmpl = (tools / "badge-release.svg.tmpl").read_text(encoding="utf-8")
    badge_tests_tmpl = (tools / "badge-tests.svg.tmpl").read_text(encoding="utf-8")
    return {
        "README.md": render_readme(readme, version, count, date_iso),
        "CITATION.cff": citation_tmpl.replace("{VERSION}", version).replace(
            "{DATE}", date_iso
        ),
        "docs/media/badge-release.svg": render_badge(
            badge_rel_tmpl, "RELEASE", f"v{version}"
        ),
        "docs/media/badge-tests.svg": render_badge(
            badge_tests_tmpl,
            "TESTS",
            f"{count} PASSING — GATES GREEN",
            f"{count} passing — gates green",
        ),
    }


# --------------------------------------------------------------------------
# The gate (Layer 2). One line per check: RS-G<n> PASS|FAIL ...
# --------------------------------------------------------------------------


class Check:
    def __init__(self, gid: str, ok: bool, surface: str, expected: str, found: str):
        self.gid, self.ok, self.surface = gid, ok, surface
        self.expected, self.found = expected, found

    def line(self) -> str:
        verdict = "PASS" if self.ok else "FAIL"
        return (
            f"RS-{self.gid} {verdict} {self.surface} "
            f"expected={self.expected} found={self.found}"
        )


class Ctx:
    def __init__(self, root: Path):
        self.root = root
        self._decl: str | None = None
        self._decl_err: str | None = None
        self._manifest: dict | None = None
        self._manifest_err: str | None = None
        self.computed_count: int | None = None
        self.suite_exit: int | None = None

    @property
    def decl(self) -> str:
        if self._decl is None:
            try:
                self._decl = declaration(self.root)
            except SurfaceError as exc:
                self._decl_err = str(exc)
                raise
        return self._decl

    @property
    def manifest(self) -> dict:
        if self._manifest is None:
            try:
                self._manifest = load_manifest(self.root)
            except SurfaceError as exc:
                self._manifest_err = str(exc)
                raise
        return self._manifest


def check_g1(ctx: Ctx, tag: str | None) -> Check:
    if tag is None:
        return Check("G1", False, "tag", f"v{ctx.decl}", "no-tag-supplied")
    found = tag[1:] if tag.startswith("v") else tag
    return Check("G1", found == ctx.decl, "tag", ctx.decl, found)


def check_g2(ctx: Ctx) -> Check:
    managed_paths = {
        e["path"]
        for e in ctx.manifest.get("managed", [])
        if e.get("kind") in {"generated", "marker-regions"}
    }
    count = ctx.computed_count
    if count is None:
        count = claimed_count(ctx.root)
    if count is None:
        return Check("G2", False, "derived-surfaces", "renderable", "no-count-source")
    rendered = render_surfaces(ctx.root, count)
    stale = []
    if set(rendered) != managed_paths:
        stale.append("manifest-surface-set-mismatch")
    for rel, content in rendered.items():
        current = (ctx.root / rel).read_text(encoding="utf-8")
        if current != content:
            stale.append(rel)
    if stale:
        return Check(
            "G2", False, "derived-surfaces", "zero-diff", ",".join(sorted(stale))
        )
    return Check("G2", True, "derived-surfaces", "zero-diff", "zero-diff")


def check_g3(ctx: Ctx) -> Check:
    head_version, head_date = changelog_head(ctx.root)
    _, cit_date = citation_fields(ctx.root)
    ok = head_version == ctx.decl and cit_date == head_date
    found = f"{head_version}@{head_date}/citation-date={cit_date}"
    return Check("G3", ok, "CHANGELOG.md-head", f"{ctx.decl}@changelog-date", found)


def check_g4(ctx: Ctx, junit_path: Path) -> Check:
    claimed = claimed_count(ctx.root)
    rc, count = run_suite(ctx.root, junit_path)
    ctx.suite_exit, ctx.computed_count = rc, count
    green = rc == 0
    ok = green and claimed is not None and count == claimed
    found = f"{count} (suite exit {rc})"
    return Check("G4", ok, "test-count", f"{claimed} from a green suite", found)


def _canon(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").rstrip("\n")


def _metadata_parts(raw: bytes) -> tuple[str | None, str]:
    text = raw.decode("utf-8", errors="replace")
    head, _, body = text.partition("\n\n")
    version = None
    for line in head.splitlines():
        if line.startswith("Version:"):
            version = line.split(":", 1)[1].strip()
    return version, body


def check_g5(ctx: Ctx, dist: Path) -> Check:
    readme = (ctx.root / "README.md").read_text(encoding="utf-8")
    readme_hash = hashlib.sha256(_canon(readme).encode()).hexdigest()[:12]
    problems: list[str] = []
    seen = 0
    for whl in sorted(dist.glob("*.whl")):
        seen += 1
        with zipfile.ZipFile(whl) as zf:
            names = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
            if not names:
                problems.append(f"{whl.name}:no-METADATA")
                continue
            version, body = _metadata_parts(zf.read(names[0]))
        body_hash = hashlib.sha256(_canon(body).encode()).hexdigest()[:12]
        if version != ctx.decl:
            problems.append(f"{whl.name}:version={version}")
        if body_hash != readme_hash:
            problems.append(f"{whl.name}:description-hash={body_hash}")
    for sdist in sorted(dist.glob("*.tar.gz")):
        seen += 1
        with tarfile.open(sdist) as tf:
            names = [n for n in tf.getnames() if n.endswith("/PKG-INFO")]
            if not names:
                problems.append(f"{sdist.name}:no-PKG-INFO")
                continue
            raw = tf.extractfile(names[0]).read()
        version, body = _metadata_parts(raw)
        body_hash = hashlib.sha256(_canon(body).encode()).hexdigest()[:12]
        if version != ctx.decl:
            problems.append(f"{sdist.name}:version={version}")
        if body_hash != readme_hash:
            problems.append(f"{sdist.name}:description-hash={body_hash}")
    if seen == 0:
        return Check("G5", False, "dist-artifacts", ctx.decl, "no-artifacts")
    if problems:
        return Check("G5", False, "dist-artifacts", ctx.decl, ",".join(problems))
    return Check(
        "G5", True, "dist-artifacts", f"{ctx.decl}/readme#{readme_hash}", "match"
    )


def check_g6(ctx: Ctx, dist: Path) -> Check:
    wheels = sorted(dist.glob("*.whl"))
    if not wheels:
        return Check("G6", False, "installed-runtime", ctx.decl, "no-wheel")
    with tempfile.TemporaryDirectory(prefix="rs-g6-") as tmp:
        venv_dir = Path(tmp) / "venv"
        venv.create(venv_dir, with_pip=True)
        py = venv_dir / "bin" / "python"
        install = subprocess.run(
            [
                str(py),
                "-m",
                "pip",
                "install",
                "--no-deps",
                "--disable-pip-version-check",
                str(wheels[0]),
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if install.returncode != 0:
            return Check(
                "G6", False, "installed-runtime", ctx.decl, "pip-install-failed"
            )
        probe = subprocess.run(
            [str(py), "-c", "import chancellor; print(chancellor.__version__)"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        found = probe.stdout.strip()
    return Check("G6", found == ctx.decl, "installed-runtime", ctx.decl, found)


def _region_lines(text: str) -> set[int]:
    lines: set[int] = set()
    for m in MARKER_RE.finditer(text):
        start = text.count("\n", 0, m.start()) + 1
        end = text.count("\n", 0, m.end()) + 1
        lines.update(range(start, end + 1))
    return lines


def check_g7(ctx: Ctx) -> Check:
    manifest = ctx.manifest
    decl = ctx.decl
    managed = {e["path"]: e for e in manifest.get("managed", [])}
    exempt_files = manifest.get("exempt_files", [])
    exempt_patterns = manifest.get("exempt_patterns", [])

    def file_exempt(rel: str) -> bool:
        for e in exempt_files:
            if "path" in e and e["path"] == rel:
                return True
            if "glob" in e and fnmatch.fnmatchcase(rel, e["glob"]):
                return True
        return False

    def pattern_exempt(rel: str, line: str) -> bool:
        return any(
            e.get("path") == rel and re.search(e["regex"], line)
            for e in exempt_patterns
        )

    offenders: list[str] = []
    for path in sorted(ctx.root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ctx.root).as_posix()
        if any(part in SKIP_DIRS for part in path.relative_to(ctx.root).parts):
            continue
        if path.suffix.lower() in BINARY_SUFFIXES or rel.endswith(".egg-info"):
            continue
        if file_exempt(rel):
            continue
        entry = managed.get(rel)
        if entry is not None and entry.get("scan") == "exempt":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        region_lines = _region_lines(text) if rel == "README.md" else set()
        for lineno, line in enumerate(text.splitlines(), start=1):
            for m in VERSION_RE.finditer(line):
                value = m.group(0)
                bare = value[1:] if value.startswith("v") else value
                if rel == "pyproject.toml":
                    if bare != decl:
                        offenders.append(f"{rel}:{lineno}:{value}")
                    continue
                if (
                    entry is not None
                    and rel != "README.md"
                    and entry.get("kind") == "generated"
                ):
                    continue  # whole-file generated surface; G2/G3 bind it
                if lineno in region_lines:
                    continue
                if pattern_exempt(rel, line):
                    continue
                offenders.append(f"{rel}:{lineno}:{value}")
    if offenders:
        shown = ",".join(offenders[:5])
        if len(offenders) > 5:
            shown += f",+{len(offenders) - 5} more"
        return Check("G7", False, "version-literals", "0-unclassified", shown)
    return Check("G7", True, "version-literals", "0-unclassified", "0-unclassified")


def check_g9(ctx: Ctx, event: dict | None) -> Check:
    if event is None:
        return Check(
            "G9", True, "dispatch-guard", "guarded-dispatch", "no-event-context"
        )
    name = event.get("event_name", "")
    if name == "release":
        return Check("G9", True, "dispatch-guard", "release-event", "release-event")
    if name == "workflow_dispatch":
        ref = event.get("ref", "")
        expected = (event.get("inputs") or {}).get("expected_version", "")
        ok = ref.startswith("refs/tags/v") and expected == ctx.decl
        found = f"ref={ref},expected_version={expected or 'absent'}"
        return Check("G9", ok, "dispatch-guard", f"tag+input=={ctx.decl}", found)
    return Check("G9", True, "dispatch-guard", "guarded-dispatch", f"event={name}")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

CHECK_SURFACES = {
    "G1": "tag",
    "G2": "derived-surfaces",
    "G3": "CHANGELOG.md-head",
    "G4": "test-count",
    "G5": "dist-artifacts",
    "G6": "installed-runtime",
    "G7": "version-literals",
    "G9": "dispatch-guard",
}


def resolve_event(args: argparse.Namespace) -> dict | None:
    if getattr(args, "event_json", None):
        return json.loads(Path(args.event_json).read_text(encoding="utf-8"))
    if getattr(args, "event_env", False):
        name = os.environ.get("RS_EVENT_NAME", "")
        if not name:
            return None
        return {
            "event_name": name,
            "ref": os.environ.get("RS_REF", ""),
            "release_tag": os.environ.get("RS_RELEASE_TAG", ""),
            "inputs": {"expected_version": os.environ.get("RS_EXPECTED_VERSION", "")},
        }
    return None


def resolve_tag(args: argparse.Namespace, event: dict | None) -> str | None:
    if getattr(args, "tag", None):
        return args.tag
    if event:
        if event.get("release_tag"):
            return str(event["release_tag"])
        ref = event.get("ref", "")
        if ref.startswith("refs/tags/"):
            return ref.rsplit("/", 1)[-1]
    return None


def run_check_set(
    root: Path,
    gids: list[str],
    tag: str | None,
    event: dict | None,
    dist: Path | None,
) -> int:
    ctx = Ctx(root)
    results: dict[str, Check] = {}
    junit_tmp: Path | None = None

    def record(gid: str, fn) -> None:
        try:
            results[gid] = fn()
        except SurfaceError as exc:
            results[gid] = Check(
                gid, False, CHECK_SURFACES[gid], "readable-inputs", f"blind:{exc}"
            )
        except Exception as exc:  # the gate's blindness is a verdict, not a crash
            results[gid] = Check(
                gid,
                False,
                CHECK_SURFACES[gid],
                "readable-inputs",
                f"blind:{type(exc).__name__}:{exc}",
            )

    # G4 first when present: its computed count feeds G2 (SPEC 3.3).
    if "G4" in gids:
        fd, tmp_name = tempfile.mkstemp(prefix="rs-junit-", suffix=".xml")
        os.close(fd)
        junit_tmp = Path(tmp_name)
        record("G4", lambda: check_g4(ctx, junit_tmp))
    for gid in gids:
        if gid == "G4":
            continue
        if gid == "G1":
            record("G1", lambda: check_g1(ctx, tag))
        elif gid == "G2":
            record("G2", lambda: check_g2(ctx))
        elif gid == "G3":
            record("G3", lambda: check_g3(ctx))
        elif gid == "G5":
            record("G5", lambda: check_g5(ctx, dist))
        elif gid == "G6":
            record("G6", lambda: check_g6(ctx, dist))
        elif gid == "G7":
            record("G7", lambda: check_g7(ctx))
        elif gid == "G9":
            record("G9", lambda: check_g9(ctx, event))
    failed = False
    for gid in gids:
        print(results[gid].line())
        failed = failed or not results[gid].ok
    if junit_tmp is not None:
        junit_tmp.unlink(missing_ok=True)
    return 1 if failed else 0


def cmd_check(args: argparse.Namespace) -> int:
    root = args.root
    event = resolve_event(args)
    tag = resolve_tag(args, event)
    if args.gate_b:
        return run_check_set(root, ["G5", "G6"], tag, event, Path(args.gate_b))
    if args.gate_a:
        return run_check_set(
            root, ["G1", "G2", "G3", "G4", "G7", "G9"], tag, event, None
        )
    if args.offline:
        return run_check_set(root, ["G2", "G7"], tag, event, None)
    return run_check_set(root, ["G2", "G3", "G7"], tag, event, None)


def cmd_render(args: argparse.Namespace) -> int:
    root = args.root
    if args.count is not None:
        count = args.count
    elif args.junitxml:
        count = count_from_junit(Path(args.junitxml))
    else:
        claimed = claimed_count(root)
        if claimed is None:
            print(
                "render: no count source (use --count or --junitxml)",
                file=sys.stderr,
            )
            return 2
        count = claimed
    try:
        rendered = render_surfaces(root, count)
    except SurfaceError as exc:
        print(f"render: {exc}", file=sys.stderr)
        return 2
    for rel, content in rendered.items():
        path = root / rel
        current = path.read_text(encoding="utf-8")
        state = "unchanged" if current == content else "updated"
        if state == "updated":
            path.write_text(content, encoding="utf-8")
        print(f"RENDER {rel} {state}")
    return 0


def cmd_count(args: argparse.Namespace) -> int:
    junit = (
        Path(args.junitxml)
        if args.junitxml
        else Path(tempfile.mkstemp(prefix="rs-junit-", suffix=".xml")[1])
    )
    try:
        _, count = run_suite(args.root, junit)
    except SurfaceError as exc:
        print(f"count: {exc}", file=sys.stderr)
        return 2
    print(count)
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    path = args.root / "CHANGELOG.md"
    if not path.is_file():
        print("notes: CHANGELOG.md is missing", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    m = CHANGELOG_HEAD_RE.search(text)
    if not m:
        print("notes: no parseable head entry", file=sys.stderr)
        return 2
    rest = text[m.end() :]
    nxt = re.search(r"^## \[", rest, re.MULTILINE)
    body = rest[: nxt.start()] if nxt else rest
    print(body.strip())
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="release_sync.py",
        description="Chancellor release-sync: render / check / count / notes.",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: the tree this tool lives in)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_render = sub.add_parser("render", help="regenerate derived surfaces")
    p_render.add_argument("--count", type=int, help="passing-test count to render")
    p_render.add_argument(
        "--junitxml", help="JUnit XML to take the count from (SPEC 2.3 formula)"
    )
    p_render.set_defaults(fn=cmd_render)

    p_check = sub.add_parser("check", help="verify-only gate mode")
    modes = p_check.add_mutually_exclusive_group()
    modes.add_argument(
        "--gate-a", action="store_true", help="pre-build set: G1-G4, G7, G9"
    )
    modes.add_argument(
        "--gate-b", metavar="DIST", help="post-build set on dist/: G5, G6"
    )
    modes.add_argument(
        "--offline", action="store_true", help="local consistency set: G2, G7"
    )
    p_check.add_argument("--tag", help="release tag for G1 (e.g. vX.Y.Z)")
    p_check.add_argument("--event-json", help="workflow event context JSON (G9)")
    p_check.add_argument(
        "--event-env",
        action="store_true",
        help="read the event context from RS_* environment variables",
    )
    p_check.set_defaults(fn=cmd_check)

    p_count = sub.add_parser("count", help="run the suite; print the passing count")
    p_count.add_argument("--junitxml", help="where to write the JUnit XML")
    p_count.set_defaults(fn=cmd_count)

    p_notes = sub.add_parser("notes", help="print the CHANGELOG head entry's prose")
    p_notes.set_defaults(fn=cmd_notes)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
