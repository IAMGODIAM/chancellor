"""Governor Policy Engine + founding packs (SPEC §2).

Covers: pack loading under the razor, the verdict matrix for Packs
001-004, rule conflict, the Chairman's by-name waiver (and its
limits), fail-closed semantics for gated classes, QUEUED-OFFBOX,
routing preconditions, and per-shard routing receipts.
"""

import json
from pathlib import Path

import pytest

from chancellor.governor_receipts import GovernorReceipts
from chancellor.packs import load_builtin_packs
from chancellor.policy import (
    EngineContext,
    PackRefusal,
    PolicyEngine,
    load_pack,
)

FIXTURES = Path(__file__).parent / "fixtures" / "governor"


def _engine(tmp_path, **ctx_kwargs):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    engine = PolicyEngine(
        load_builtin_packs(receipts=receipts),
        receipts=receipts,
        context=EngineContext(**ctx_kwargs),
    )
    return engine, receipts


def _descriptor(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_builtin_packs_load_with_foundings(tmp_path):
    packs = load_builtin_packs()
    assert [p.name for p in packs] == [
        "compute-routing",
        "fetch-preflight",
        "submission-gate",
        "money-staging",
    ]
    assert [len(p.rules) for p in packs] == [5, 4, 2, 3]
    for pack in packs:
        assert pack.founded_by  # every pack cites its founding (the razor)
        for rule in pack.rules:
            assert rule.founded_by


def test_burn_cap_is_a_named_slot_with_no_value():
    pack = load_builtin_packs()[0]
    assert pack.config["burn_cap_slot"] == "lambda_burn_cap_usd"
    # The figure is the Chairman's to set (SPEC §9) — never invented.
    assert pack.config["lambda_burn_cap_usd"] is None


def test_rule_without_founding_is_refused_and_receipted(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    bad = {
        "name": "bad-pack",
        "version": "0",
        "founded_by": "Standing order, dated 2026-11-03",
        "rules": [
            {
                "id": "BAD.RULE",
                # no founded_by — the razor test (A6)
                "act_classes": ["compute"],
                "action": "allow",
                "receipt": "policy-verdict",
                "override": "none",
                "measured_by": "nothing",
            }
        ],
    }
    with pytest.raises(PackRefusal, match="founded_by"):
        load_pack(bad, receipts=receipts)
    refusals = [
        e
        for e in receipts.entries(kind="policy-verdict")
        if e.get("outcome") == "pack-refused"
    ]
    assert len(refusals) == 1
    assert refusals[0]["pack"] == "bad-pack"


def test_pack_without_founding_is_refused(tmp_path):
    with pytest.raises(PackRefusal):
        load_pack({"name": "orphan", "version": "0", "rules": []})


def test_undated_founding_is_refused(tmp_path):
    bad = {
        "name": "bad-pack",
        "version": "0",
        "founded_by": "a failure we all remember",
        "rules": [
            {
                "id": "BAD.RULE",
                "founded_by": "a failure we all remember",
                "act_classes": ["compute"],
                "action": "allow",
                "receipt": "policy-verdict",
                "override": "none",
                "measured_by": "nothing",
            }
        ],
    }
    with pytest.raises(PackRefusal):
        load_pack(bad)


def test_compute_routing_matrix(tmp_path):
    engine, _ = _engine(tmp_path)
    gpu = engine.check(_descriptor("act_gpu_job.json"))
    assert gpu.action == "route:lambda-gpu"
    assert gpu.rule_ids == ["COMPUTE.GPU"]
    corpus = engine.check(_descriptor("act_corpus_job.json"))
    assert corpus.action == "route:lambda"
    assert corpus.rule_ids == ["COMPUTE.HEAVY"]
    light = engine.check(_descriptor("act_light_job.json"))
    assert light.action == "allow:local"
    assert light.rule_ids == ["COMPUTE.LIGHT"]


def test_heavy_triggers_are_measured_not_remembered(tmp_path):
    engine, _ = _engine(tmp_path)
    # Exactly at the threshold does not fire; one byte over does.
    at = engine.check({"act_class": "compute", "input_bytes": 500_000_000})
    assert at.action == "allow:local"
    over = engine.check({"act_class": "compute", "input_bytes": 500_000_001})
    assert over.action == "route:lambda"
    by_class = engine.check({"act_class": "compute", "wall_clock_class": "long-runner"})
    assert by_class.rule_ids == ["COMPUTE.HEAVY"]
    by_memory = engine.check(
        {
            "act_class": "compute",
            "peak_memory_bytes": 9_000,
            "box_safe_envelope_bytes": 8_000,
        }
    )
    assert by_memory.rule_ids == ["COMPUTE.HEAVY"]


def test_burst_fans_out_one_receipt_per_shard(tmp_path):
    engine, receipts = _engine(tmp_path)
    verdict = engine.check(
        {"act_class": "compute", "shard_count": 4, "shards_heavy": True}
    )
    assert verdict.action == "route:lambda"
    routing = receipts.entries(kind="routing")
    shards = [e for e in routing if "shard" in e]
    assert len(shards) == 4
    assert {e["shard"] for e in shards} == {0, 1, 2, 3}


def test_box_protect_fires_in_running_phase_only(tmp_path):
    engine, _ = _engine(tmp_path)
    running = engine.check(
        {
            "act_class": "compute",
            "phase": "running",
            "heavy_running_locally": True,
        }
    )
    assert running.action == "stage:migrate-or-justify"
    # Launch rules do not leak into the running phase.
    gpu_running = engine.check(
        {"act_class": "compute", "phase": "running", "requires_gpu": True}
    )
    assert gpu_running.rule_ids == []


def test_route_unavailable_lambda_queues_offbox(tmp_path):
    engine, _ = _engine(tmp_path)
    verdict = engine.check(
        {"act_class": "compute", "requires_gpu": True, "lambda_available": False}
    )
    assert verdict.action == "queue:offbox"


def test_route_preconditions_enforced(tmp_path):
    engine, _ = _engine(tmp_path)
    bad_context = engine.check(
        {
            "act_class": "compute",
            "requires_gpu": True,
            "launch_context": "subagent",
            "checkpointed": True,
        }
    )
    assert bad_context.action == "stage:routing-preconditions"
    assert bad_context.unmet_preconditions
    uncheckpointed = engine.check(
        {
            "act_class": "compute",
            "requires_gpu": True,
            "launch_context": "persistent",
            "checkpointed": False,
        }
    )
    assert uncheckpointed.action == "stage:routing-preconditions"


def test_money_pack_staging(tmp_path):
    engine, _ = _engine(tmp_path)
    staged = engine.check({"act_class": "money", "amount_usd": 25})
    assert staged.action == "stage:chairman-approval"
    lane = engine.check(
        {"act_class": "send", "preapproved_lane": "sawdust-daily-editions"}
    )
    assert lane.action == "allow"
    approved = engine.check({"act_class": "deploy", "chairman_approved": True})
    assert approved.action == "allow"
    # An unnamed lane is not a pre-approved lane.
    other = engine.check({"act_class": "send", "preapproved_lane": "my-lane"})
    assert other.action == "stage:chairman-approval"


def test_fetch_pack_preflight_and_grants(tmp_path):
    engine, _ = _engine(tmp_path)
    multi = engine.check(
        {
            "act_class": "fetch",
            "domains": ["a.example", "b.example"],
            "preflight_done": False,
        }
    )
    assert multi.action == "stage:preflight"
    done = engine.check(
        {
            "act_class": "fetch",
            "domains": ["a.example", "b.example"],
            "granted_domains": ["a.example", "b.example"],
            "preflight_done": True,
        }
    )
    assert done.action == "allow"
    material = engine.check({"act_class": "fetch", "material_only": True})
    assert material.action == "allow"


def test_conflicting_rules_stage_with_both_receipts(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")

    def rule(rid, action):
        return {
            "id": rid,
            "founded_by": "Test failure, dated 2026-11-03",
            "act_classes": ["compute"],
            "when": {"marker": True},
            "action": action,
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 50,
            "measured_by": "descriptor marker field",
        }

    pack = load_pack(
        {
            "name": "conflict-pack",
            "version": "0",
            "founded_by": "Test failure, dated 2026-11-03",
            "rules": [rule("X.ALLOW", "allow"), rule("X.DENY", "deny")],
        }
    )
    engine = PolicyEngine([pack], receipts=receipts)
    verdict = engine.check({"act_class": "compute", "marker": True})
    assert verdict.action == "stage:chairman-conflict"
    assert verdict.conflict == ("X.ALLOW", "X.DENY")
    assert len(verdict.receipt_ids) == 2
    # A waiver never resolves a contradiction in the orders themselves.
    waived = engine.check(
        {"act_class": "compute", "marker": True, "chairman_waiver": "Chairman"}
    )
    assert waived.action == "stage:chairman-conflict"


def test_waiver_only_where_the_rule_allows_it(tmp_path):
    engine, receipts = _engine(tmp_path)
    # SUBMIT.MISSING carries override chairman-by-name.
    waived = engine.check(
        {
            "act_class": "submission",
            "artifact": "pkg",
            "chairman_waiver": "Israel Lee Armstead",
        }
    )
    assert waived.action == "allow"
    assert waived.override_by == "Israel Lee Armstead"
    gate_entries = receipts.entries(kind="gate")
    assert any(e.get("override_by") == "Israel Lee Armstead" for e in gate_entries)
    # MONEY.STAGE carries override none — a waiver field does not move it.
    money = engine.check(
        {"act_class": "money", "chairman_waiver": "Israel Lee Armstead"}
    )
    assert money.action == "stage:chairman-approval"


def test_engine_down_fails_closed_for_gated_classes(tmp_path):
    receipts = GovernorReceipts(tmp_path / "log.jsonl")
    engine = PolicyEngine.unavailable(receipts=receipts)
    money = engine.check({"act_class": "money"})
    assert money.action == "deny"
    assert money.gated
    compute = engine.check({"act_class": "compute"})
    assert compute.action == "allow"
    assert compute.degraded
    outcomes = {e.get("outcome") for e in receipts.entries(kind="policy-verdict")}
    assert "engine-down-deny" in outcomes
    assert "degraded" in outcomes
