"""Acceptance A1–A8 (SPEC §7) — the Governor is not done until these
pass, cold. Each test is named for its acceptance item and states,
in its docstring, the closest honest automated form where the item
also has a human or fleet-scale half.
"""

import json
import shutil
from pathlib import Path

import pytest

from chancellor import cli
from chancellor.census_bootstrap import bootstrap
from chancellor.governor_receipts import RECEIPT_KINDS, GovernorReceipts
from chancellor.manifest import Registry, file_hash
from chancellor.packs import load_builtin_packs
from chancellor.policy import EngineContext, PolicyEngine
from chancellor.preload import issue_preload
from chancellor.verify_log import verify_log

FIXTURES = Path(__file__).parent / "fixtures" / "governor"
REAL_FILINGS = Path(
    "~/workspace/war-room/2026-11-03-wisdom-council-empire-sweep/lanes"
).expanduser()


def _engine(tmp_path, **ctx):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    engine = PolicyEngine(
        load_builtin_packs(receipts=receipts),
        receipts=receipts,
        context=EngineContext(**ctx),
    )
    return engine, receipts


def test_a1_lambda_test(tmp_path):
    """A1: a synthetic GPU job and a >500 MB corpus job, checked by a
    fresh engine with no doctrine in context, route off-box with
    routing receipts — zero human reminders. (The pre-Governor
    failing control is the historical record the pack cites, not
    something a test can re-run.)"""
    engine, receipts = _engine(tmp_path)
    for fixture, target in (
        ("act_gpu_job.json", "route:lambda-gpu"),
        ("act_corpus_job.json", "route:lambda"),
    ):
        descriptor = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
        verdict = engine.check(descriptor)
        assert verdict.action == target
    routing = receipts.entries(kind="routing")
    assert len(routing) == 2
    assert {e["rule"] for e in routing} == {"COMPUTE.GPU", "COMPUTE.HEAVY"}


def test_a2_stale_canon_test(tmp_path):
    """A2: a canon copy in an archive tree is deliberately regressed;
    one verification cycle mints a drift receipt naming expected vs
    found, and the corrected copy is pushed."""
    canonical = tmp_path / "canon" / "frame.md"
    canonical.parent.mkdir()
    canonical.write_text("the canon, current\n", encoding="utf-8")
    archive_copy = tmp_path / "archive" / "frame.md"
    archive_copy.parent.mkdir()
    archive_copy.write_text("the canon, regressed\n", encoding="utf-8")
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    registry = Registry(tmp_path / "registry.json")
    registry.add(
        {
            "name": "frame-archive-copy",
            "kind": "canon",
            "purpose": "archive copy of the frame canon",
            "canonical_location": str(archive_copy),
            "tier": "mirror",
            "state": "unverified",
            "mirror_of": str(canonical),
        }
    )
    regressed_hash = file_hash(archive_copy)
    report = registry.verify(receipts=receipts)
    assert len(report["findings"]) == 1
    finding = report["findings"][0]
    assert finding["expected"] == file_hash(canonical)
    assert finding["found"] == regressed_hash
    drift = receipts.entries(kind="drift")
    assert len(drift) == 1
    assert drift[0]["expected"] == file_hash(canonical)
    assert drift[0]["found"] != drift[0]["expected"]
    assert archive_copy.read_text(encoding="utf-8") == "the canon, current\n"


def test_a3_preload_test(tmp_path):
    """A3: a compute-heavy preload names the compute rules and is
    versioned; when canon changes, the next issuance's version
    differs and the old version shows invalidated in the Registry."""
    registry = Registry(tmp_path / "registry.json")
    canon = tmp_path / "canon.md"
    canon.write_text("v1\n", encoding="utf-8")
    registry.add(
        {
            "name": "house-canon",
            "kind": "canon",
            "purpose": "canon",
            "canonical_location": str(canon),
            "tier": "canonical",
            "state": "verified",
            "content_hash": file_hash(canon),
            "operative_text": "Measure first.",
        }
    )
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    first = issue_preload(registry, receipts, "compute-heavy", "heavy job")
    assert "COMPUTE.HEAVY" in first["text"]
    assert "route:lambda" in first["text"]

    canon.write_text("v2\n", encoding="utf-8")
    entry = dict(registry.get("house-canon"))
    entry["content_hash"] = file_hash(canon)
    registry.add(entry, receipts=receipts)

    versions = registry.meta["preload_versions"]["compute-heavy"]
    assert first["stamp"] in versions["invalidated"]
    second = issue_preload(registry, receipts, "compute-heavy", "heavy job")
    assert second["stamp"] != first["stamp"]


def test_a4_gate_test(tmp_path):
    """A4: a submission without a PASS receipt is blocked fail-closed;
    with one (minted on the same shipped spine by the gate lane) it
    proceeds; the Chairman's by-name waiver works and receipts as an
    override. All three paths mint gate receipts."""
    receipts = GovernorReceipts(tmp_path / "log.jsonl")

    def gate_lookup(descriptor):
        for entry in receipts.entries(kind="gate"):
            if (
                entry.get("artifact") == descriptor.get("artifact")
                and entry.get("verdict") == "PASS"
            ):
                return entry
        return None

    engine = PolicyEngine(
        load_builtin_packs(receipts=receipts),
        receipts=receipts,
        context=EngineContext(gate_lookup=gate_lookup),
    )
    blocked = engine.check({"act_class": "submission", "artifact": "paper-1"})
    assert blocked.action == "deny"

    receipts.mint(
        "gate", {"artifact": "paper-1", "verdict": "PASS", "lane": "gate-lane"}
    )
    allowed = engine.check({"act_class": "submission", "artifact": "paper-1"})
    assert allowed.action == "allow"

    waived = engine.check(
        {
            "act_class": "submission",
            "artifact": "paper-2",
            "chairman_waiver": "Israel Lee Armstead",
        }
    )
    assert waived.action == "allow"
    assert waived.override_by == "Israel Lee Armstead"
    gate_entries = receipts.entries(kind="gate")
    assert any(e.get("outcome") == "verdict" for e in gate_entries)
    assert any(e.get("override_by") == "Israel Lee Armstead" for e in gate_entries)


def test_a5_freeze_test(tmp_path):
    """A5: with the fetch-freeze flag set in the Registry, a
    fetch-capable lane's new-domain touch is denied pre-act with a
    receipt; granted-domain work proceeds. The engine is the CLI's
    own wiring, so the flag path tested is the flag path shipped."""
    state = tmp_path / "state"
    state.mkdir()
    registry = Registry(state / "registry.json")
    registry.meta["fetch_freeze"] = True
    registry.save()
    receipts = GovernorReceipts(state / "audit-log.jsonl")
    engine = cli._governor_engine(receipts, registry)

    denied = engine.check(
        {
            "act_class": "fetch",
            "domains": ["new-domain.example"],
            "granted_domains": [],
            "preflight_done": True,
        }
    )
    assert denied.action == "deny"
    assert denied.rule_ids == ["FETCH.FREEZE"]
    granted = engine.check(
        {
            "act_class": "fetch",
            "domains": ["known.example"],
            "granted_domains": ["known.example"],
            "preflight_done": True,
        }
    )
    assert granted.action == "allow"
    verdicts = receipts.entries(kind="policy-verdict")
    assert any(e.get("rule") == "FETCH.FREEZE" for e in verdicts)


def test_a6_razor_test(tmp_path):
    """A6: a proposed rule without a founding citation is refused by
    the pack loader, and the refusal is receipted."""
    from chancellor.policy import PackRefusal, load_pack

    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    pack = {
        "name": "razor-pack",
        "version": "0",
        "founded_by": "A dated founding failure, 2026-11-03",
        "rules": [
            {
                "id": "RAZOR.NAKED",
                "act_classes": ["compute"],
                "action": "allow",
                "receipt": "policy-verdict",
                "override": "none",
                "measured_by": "nothing measurable",
            }
        ],
    }
    with pytest.raises(PackRefusal):
        load_pack(pack, receipts=receipts)
    refusals = [
        e
        for e in receipts.entries(kind="policy-verdict")
        if e.get("outcome") == "pack-refused"
    ]
    assert len(refusals) == 1
    assert "founded_by" in refusals[0]["reason"]


def test_a7_rebuild_test_fixture_census(tmp_path):
    """A7 (in-repo form): the Registry bootstrapped from census
    filings in the Empire Sweep format reconciles with zero
    unexplained rows, and the registry file — read back alone, as
    from an archive copy — enumerates the estate."""
    report = bootstrap(FIXTURES / "census", tmp_path / "registry.json")
    assert report["unexplained"] == []
    assert report["checks"] and all(c["ok"] for c in report["checks"])
    assert report["deduped"] >= 2  # cross-lane duplicates collapsed
    reopened = Registry(tmp_path / "registry.json")
    names = {e["name"] for e in reopened.entries}
    assert "manifest-registry" in names  # the register registers itself
    assert "cron-definitions" in names
    assert reopened.get("cron-definitions")["count"] == 4


@pytest.mark.skipif(
    not REAL_FILINGS.exists(),
    reason="the live Empire Sweep filings are not on this machine",
)
def test_a7_rebuild_test_live_census(tmp_path):
    """A7 (live form): the same reconciliation against the actual
    2026-11-03 Empire Sweep filings — zero unexplained rows."""
    report = bootstrap(REAL_FILINGS, tmp_path / "registry.json")
    assert report["unexplained"] == []
    assert report["entries_total"] > 200


def test_a8_offline_verification(tmp_path):
    """A8: a sample of each receipt kind, checkpointed, verifies
    offline with the shipped verifier using only copied files — the
    archive-copy posture: no live state is consulted."""
    state = tmp_path / "state"
    state.mkdir()
    receipts = GovernorReceipts(state / "audit-log.jsonl")
    for kind in RECEIPT_KINDS:
        receipts.mint(kind, {"rule": "A8.SAMPLE", "artifact": "a8-sample"})
    receipts.checkpoint()

    archive = tmp_path / "archive"
    archive.mkdir()
    log_copy = archive / "audit-log.jsonl"
    shutil.copyfile(state / "audit-log.jsonl", log_copy)
    checkpoint_src = receipts.log.checkpoint_path
    checkpoint_copy = archive / checkpoint_src.name
    shutil.copyfile(checkpoint_src, checkpoint_copy)

    result = verify_log(log_copy, checkpoint_copy)
    assert result.ok, result.failures
