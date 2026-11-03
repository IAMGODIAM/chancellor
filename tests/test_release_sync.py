"""Unit tests for tools/release_sync.py (release-sync SPEC Layers 1-2).

These tests build synthetic trees in tmp_path; they never run the full
suite, never build distributions, and never touch the network. The
acceptance battery they back (A5/A7/A8/A13) runs in full in the
release-sync build workspace.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def load_tool():
    spec = importlib.util.spec_from_file_location(
        "release_sync", REPO / "tools" / "release_sync.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rs = load_tool()

README_FIXTURE = """# Fixture

<!-- release-sync:TESTS-BADGE-ALT -->
<a href="https://example.invalid/actions"><img
src="docs/media/badge-tests.svg" alt="Tests: 1 passing — gates green"></a>
<!-- /release-sync:TESTS-BADGE-ALT -->
<!-- release-sync:RELEASE-BADGE -->
<a href="https://example.invalid/releases/tag/v0.1.0"><img
src="docs/media/badge-release.svg" alt="Release: v0.1.0"></a>
<!-- /release-sync:RELEASE-BADGE -->

<!-- release-sync:STATUS-LINE -->
**Status — Jan 1, 2026:** v0.1.0. Fixture prose follows the prefix.
<!-- /release-sync:STATUS-LINE -->

<!-- release-sync:TESTS-LINE -->
**Tests:** 1 passing, 0 failing — fixture prose.
<!-- /release-sync:TESTS-LINE -->

A paragraph outside any marker region, carrying no version shapes.

<!-- release-sync:WHATSNEW-HEADING -->
## What's new in 0.1.0
<!-- /release-sync:WHATSNEW-HEADING -->

Body of the fixture release notes.
"""


def make_tree(tmp_path: Path, version: str = "2.0.0", date: str = "2026-11-04") -> Path:
    root = tmp_path / "tree"
    (root / "tools").mkdir(parents=True)
    (root / "docs" / "media").mkdir(parents=True)
    (root / "src" / "chancellor").mkdir(parents=True)
    for src in (REPO / "tools").rglob("*"):
        if src.is_file():
            dst = root / "tools" / src.relative_to(REPO / "tools")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src.read_bytes())
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "chancellor"\nversion = "{version}"\n', encoding="utf-8"
    )
    (root / "README.md").write_text(README_FIXTURE, encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        f"# Changelog\n\n## [{version}] — {date}\n\nFixture notes.\n",
        encoding="utf-8",
    )
    (root / "CITATION.cff").write_text("placeholder\n", encoding="utf-8")
    (root / "docs" / "media" / "badge-release.svg").write_text("x\n", encoding="utf-8")
    (root / "docs" / "media" / "badge-tests.svg").write_text("x\n", encoding="utf-8")
    return root


def test_count_formula():
    xml = textwrap.dedent(
        """\
        <testsuites>
          <testsuite name="a" tests="10" failures="1" errors="1" skipped="2"/>
          <testsuite name="b" tests="5" failures="0" errors="0" skipped="0"/>
        </testsuites>
        """
    )
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False) as fh:
        fh.write(xml)
        path = Path(fh.name)
    # (10 - 1 - 1 - 2) + (5 - 0 - 0 - 0) = 11
    assert rs.count_from_junit(path) == 11


def test_render_idempotent_and_surgical(tmp_path):
    root = make_tree(tmp_path)
    rendered = rs.render_surfaces(root, 42)
    for rel, content in rendered.items():
        (root / rel).write_text(content, encoding="utf-8")
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert "**Status — Nov 4, 2026:** v2.0.0." in readme
    assert "**Tests:** 42 passing" in readme
    assert 'alt="Tests: 42 passing — gates green"' in readme
    assert "releases/tag/v2.0.0" in readme
    assert "## What's new in 2.0.0" in readme
    # A hand edit outside the markers survives a second render, byte-exact,
    # and the second render is a zero diff (idempotence).
    edited = readme.replace(
        "A paragraph outside any marker region, carrying no version shapes.",
        "A hand-edited paragraph outside any marker region.",
    )
    (root / "README.md").write_text(edited, encoding="utf-8")
    again = rs.render_surfaces(root, 42)
    assert again["README.md"] == edited
    for rel, content in again.items():
        assert (root / rel).read_text(encoding="utf-8") == content


def test_badge_geometry_deterministic():
    template = (REPO / "tools" / "templates" / "badge-release.svg.tmpl").read_text(
        encoding="utf-8"
    )
    one = rs.render_badge(template, "RELEASE", "v2.0.0")
    two = rs.render_badge(template, "RELEASE", "v2.0.0")
    assert one == two
    table = rs.charwidths(template)
    tl = rs.text_width_px("v2.0.0", table)
    assert f'textLength="{tl}"' in one
    assert f'width="{rs.text_width_px("RELEASE", table) + 12 + tl + 12}"' in one


def test_scan_respects_the_record(tmp_path):
    root = make_tree(tmp_path)
    for rel, content in rs.render_surfaces(root, 42).items():
        (root / rel).write_text(content, encoding="utf-8")
    (root / "BUILD-LOG.md").write_text(
        "## entry\nShipped 1.0.0 on an old tree; later 0.9.0 in a soak.\n",
        encoding="utf-8",
    )
    (root / "docs" / "evidence").mkdir(exist_ok=True)
    (root / "docs" / "evidence" / "run.md").write_text(
        "Measured on the v0.5.0 tree.\n", encoding="utf-8"
    )
    ctx = rs.Ctx(root)
    result = rs.check_g7(ctx)
    assert result.ok, result.line()
    # A planted living literal is caught, with path and line.
    (root / "docs" / "notes.md").write_text(
        "Some doc.\ncurrent release: v0.0.1\n", encoding="utf-8"
    )
    result = rs.check_g7(rs.Ctx(root))
    assert not result.ok
    assert "docs/notes.md:2" in result.line()


def test_gate_blindness_is_a_verdict(tmp_path, capsys):
    root = make_tree(tmp_path)
    (root / "CHANGELOG.md").unlink()
    rc = rs.main(["--root", str(root), "check", "--gate-a", "--tag", "v2.0.0"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "RS-G3 FAIL" in out


def test_dispatch_guard():
    ctx = rs.Ctx(REPO)
    branch = {
        "event_name": "workflow_dispatch",
        "ref": "refs/heads/feature-x",
        "inputs": {"expected_version": "1.2.1"},
    }
    assert not rs.check_g9(ctx, branch).ok
    tag = {
        "event_name": "workflow_dispatch",
        "ref": "refs/tags/v1.2.1",
        "inputs": {"expected_version": "1.2.1"},
    }
    decl = rs.declaration(REPO)
    tag["inputs"]["expected_version"] = decl
    tag["ref"] = f"refs/tags/v{decl}"
    assert rs.check_g9(ctx, tag).ok
    assert rs.check_g9(ctx, {"event_name": "release"}).ok


def test_changelog_head_and_notes(tmp_path):
    root = make_tree(tmp_path)
    assert rs.changelog_head(root) == ("2.0.0", "2026-11-04")
    rc = rs.main(["--root", str(root), "notes"])
    assert rc == 0


def test_scan_ignores_generated_output(tmp_path):
    root = make_tree(tmp_path)
    for rel, content in rs.render_surfaces(root, 42).items():
        (root / rel).write_text(content, encoding="utf-8")
    egg = root / "src" / "chancellor.egg-info"
    egg.mkdir(parents=True)
    (egg / "PKG-INFO").write_text(
        "Metadata-Version: 2.1\nVersion: 2.0.0\n\nShipped v1.0.0 notes.\n",
        encoding="utf-8",
    )
    (root / "dist").mkdir()
    (root / "dist" / "notes.txt").write_text("built at 0.0.1\n", encoding="utf-8")
    result = rs.check_g7(rs.Ctx(root))
    assert result.ok, result.line()


def test_gate_b_dist_binds_to_root(tmp_path):
    import zipfile

    root = make_tree(tmp_path)
    dist = root / "dist"
    dist.mkdir()
    with zipfile.ZipFile(dist / "chancellor-2.0.0-py3-none-any.whl", "w") as zf:
        zf.writestr(
            "chancellor-2.0.0.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: chancellor\nVersion: 9.9.9\n\n",
        )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO / "tools" / "release_sync.py"),
            "--root",
            str(root),
            "check",
            "--gate-b",
            "dist",
        ],
        capture_output=True,
        text=True,
        cwd=elsewhere,
    )
    # A relative --gate-b path binds to --root, never to the caller's cwd:
    # the wheel under root/dist is found (and fails on its merits).
    assert "no-artifacts" not in proc.stdout
    assert "no-wheel" not in proc.stdout
    assert "RS-G5 FAIL" in proc.stdout


def test_version_derivation_uninstalled(tmp_path):
    """SPEC 2.2 leg 2: no dist-info on the path -> pyproject fallback."""
    probe = textwrap.dedent(
        """\
        import importlib.metadata
        try:
            importlib.metadata.version("chancellor")
        except importlib.metadata.PackageNotFoundError:
            pass
        else:
            raise SystemExit("dist-info present: leg 2 precondition violated")
        import chancellor
        print(chancellor.__version__)
        """
    )
    script = tmp_path / "probe.py"
    script.write_text(probe, encoding="utf-8")
    env = {"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"}
    proc = subprocess.run(
        [sys.executable, str(script)], capture_output=True, text=True, env=env
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == rs.declaration(REPO)
