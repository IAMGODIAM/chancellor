"""Suite B (Stage W4) — real CrewRunner tasks under a deterministic
fault manifest. These tests pin the accounting rules the council ruled:
triggered-only denominators, drift/divergence/displacement as three
separate measures (AM-4), timing in its own denominator (AM-3), and
the zero-denominator guards (red-team K5)."""
from chancellor.evals import suite_b
from chancellor.evals.suite_b_tasks import TASKS, TASKS_BY_ID
from chancellor.evals.suite_b_world import (FAULT_CRASH, FAULT_OMISSION,
                                         FAULT_VALUE, SUB_TIMING,
                                         FaultEntry, FaultInjector,
                                         ScriptedAgent, ToolBelt, World,
                                         suite_transport)
from chancellor.api_client import CostMeter, MetaModelClient

SEED = 20261029


def _manifests(task, seed=SEED):
    manifests, _ = suite_b.build_manifest(seed, (task,))
    return manifests


# -- world / predicate correctness ---------------------------------------

def test_every_task_clean_run_passes_predicate_at_full_score():
    for task in TASKS:
        clean = suite_b.clean_reference_state(task)
        predicate, score = suite_b.score_state(task, clean)
        assert predicate, f"{task.id} clean run fails its own predicate"
        assert score == 100.0, f"{task.id} clean score {score} != 100"


def test_clean_runs_complete_in_both_arms():
    task = TASKS_BY_ID["B04"]
    clean_state = suite_b.clean_reference_state(task)
    for arm in ("governed", "ungoverned"):
        o = suite_b.run_configuration(task, arm, [], "clean",
                                      clean_state=clean_state)
        assert o.claimed_complete and o.predicate_pass and o.success
        assert not o.drift and not o.divergence and not o.displacement
        assert o.cost_usd > 0          # metered, not self-reported


def test_workers_never_emit_scores():
    task = TASKS_BY_ID["B01"]
    world = World(task.seed_state)
    client = MetaModelClient(transport=suite_transport, meter=CostMeter())
    belt = ToolBelt(world, FaultInjector([]), client,
                    suite_b.WORKER_MODEL, task.id)
    agent = ScriptedAgent(task, world, belt)
    for step in task.steps:
        artifact = agent.run_step(step)
        assert "scores" not in artifact
        assert "scores" not in (artifact.get("data") or {})


# -- manifest determinism ---------------------------------------------------

def test_manifest_determinism_same_seed_same_hash():
    m1, h1 = suite_b.build_manifest(7, TASKS[:3])
    m2, h2 = suite_b.build_manifest(7, TASKS[:3])
    assert h1 == h2 and len(h1) == 64
    assert {k: [e.to_dict() for e in v] for k, v in m1.items()} == \
           {k: [e.to_dict() for e in v] for k, v in m2.items()}


# -- fault classes demonstrably inject --------------------------------------

def test_value_fault_corrupts_state():
    task = TASKS_BY_ID["B01"]
    manifests = _manifests(task)
    clean = suite_b.clean_reference_state(task)
    o = suite_b.run_configuration(task, "ungoverned",
                                  manifests[(task.id, "value")], "value",
                                  clean_state=clean)
    # balance 1200 scaled x10 -> closing = 12000 + 350
    assert o.final_state["closing_balance"] == 12350
    assert not o.predicate_pass


def test_crash_fault_kills_mid_task_and_harness_records_it():
    task = TASKS_BY_ID["B03"]
    manifests = _manifests(task)
    o = suite_b.run_configuration(task, "ungoverned",
                                  manifests[(task.id, "crash")], "crash")
    assert o.halted and not o.claimed_complete
    assert "ToolCrash" in (o.halt_reason or "")
    assert o.steps_executed < len(task.steps)
    assert task.result_key not in o.final_state   # died before the store


def test_omission_double_defeats_retry_and_aborts_honestly():
    task = TASKS_BY_ID["B02"]
    manifests = _manifests(task)
    o = suite_b.run_configuration(task, "ungoverned",
                                  manifests[(task.id, "omit")], "omit")
    assert o.halted and not o.claimed_complete and not o.drift
    assert len(o.triggered) == 2                  # both calls fired


# -- the governed/ungoverned delta, made visible -----------------------------

def test_governed_halts_on_instrument_failure_ungoverned_drifts():
    task = TASKS_BY_ID["B01"]
    manifests = _manifests(task)
    entries = manifests[(task.id, "value")]
    clean = suite_b.clean_reference_state(task)
    g = suite_b.run_configuration(task, "governed", entries, "value",
                                  clean_state=clean)
    u = suite_b.run_configuration(task, "ungoverned", entries, "value",
                                  clean_state=clean)
    assert g.halted and not g.claimed_complete and not g.drift
    assert "payload_integrity" in (g.halt_reason or "")
    assert u.claimed_complete and u.drift
    # divergence: downstream keys changed beyond the fault's direct effect
    assert u.divergence and "closing_balance" not in u.diverged_keys
    assert "summary" in u.diverged_keys


def test_displacement_is_not_drift():
    task = TASKS_BY_ID["B05"]
    manifests = _manifests(task)
    clean = suite_b.clean_reference_state(task)
    o = suite_b.run_configuration(task, "ungoverned",
                                  manifests[(task.id, "timing")], "timing",
                                  clean_state=clean)
    assert o.claimed_complete and o.predicate_pass     # state ends right
    assert o.displacement and not o.drift              # but the work fell
    assert o.outcome_score == 70.0                     # enrich's 30 lost


# -- denominator discipline ----------------------------------------------------

def test_untriggered_faults_leave_every_denominator():
    task = TASKS_BY_ID["B01"]
    entries = [
        FaultEntry(id="T-crash", task_id=task.id, manifest_id="custom",
                   step="fetch_b", call=0, fault=FAULT_CRASH),
        FaultEntry(id="T-value-late", task_id=task.id, manifest_id="custom",
                   step="enrich", call=0, fault=FAULT_VALUE,
                   transform="replace", replacement=999,
                   direct_keys=(task.quality_key,)),
    ]
    o = suite_b.run_configuration(task, "ungoverned", entries, "custom")
    assert o.halted                                   # crash at fetch_b
    assert [t["id"] for t in o.triggered] == ["T-crash"]
    assert o.untriggered_ids == ["T-value-late"]
    arm = suite_b.ArmReport(arm="ungoverned", outcomes=[o])
    assert arm.triggered_by_class[FAULT_VALUE] == 0   # never fired, never counted
    assert arm.triggered_by_class[FAULT_CRASH] == 1


def test_timing_has_its_own_denominator():
    task = TASKS_BY_ID["B06"]
    manifests = _manifests(task)
    clean = suite_b.clean_reference_state(task)
    o = suite_b.run_configuration(task, "ungoverned",
                                  manifests[(task.id, "timing")], "timing",
                                  clean_state=clean)
    arm = suite_b.ArmReport(arm="ungoverned", outcomes=[o])
    # The timing fault is invisible to the headline recovery rate...
    assert arm.recovery_rate == "n/a (no triggered faults)"
    # ...and fully visible in its own.
    assert arm.timing_recovery_rate == 1.0
    assert arm.triggered_by_class[SUB_TIMING] == 1


# -- hand-computed drift accounting ---------------------------------------------

def test_drift_accounting_hand_computed():
    task = TASKS_BY_ID["B01"]
    manifests = _manifests(task)
    clean = suite_b.clean_reference_state(task)
    drifted = suite_b.run_configuration(task, "ungoverned",
                                        manifests[(task.id, "value")],
                                        "value", clean_state=clean)
    clean_run = suite_b.run_configuration(task, "ungoverned", [], "clean",
                                          clean_state=clean)
    arm = suite_b.ArmReport(arm="ungoverned", outcomes=[drifted, clean_run])
    assert arm.runs == 2
    # Both runs CLAIM completion — that is precisely why completion
    # alone is not the metric. Only one claim is backed by the state.
    assert arm.completion_rate == 1.0
    assert arm.successes == 1
    assert arm.drift_events == 1
    assert arm.drift_per_injected_run == 1.0
    assert arm.drift_among_unrecovered_value == 1.0
    assert arm.recovery_rate == 0.0          # the value fault never recovered
    # Cost per success counts ONLY the clean run as a success but ALL
    # spend in the numerator (Scout 3 B7).
    assert arm.cost_per_success == round(
        (drifted.cost_usd + clean_run.cost_usd) / 1, 6)
    assert arm.wasted_cost_share == round(
        drifted.cost_usd / (drifted.cost_usd + clean_run.cost_usd), 4)


# -- zero-denominator guards (red-team K5) ---------------------------------------

def test_zero_denominator_guards():
    task = TASKS_BY_ID["B01"]
    clean = suite_b.clean_reference_state(task)
    clean_run = suite_b.run_configuration(task, "governed", [], "clean",
                                          clean_state=clean)
    arm = suite_b.ArmReport(arm="governed", outcomes=[clean_run])
    assert arm.recovery_rate == "n/a (no triggered faults)"
    assert arm.timing_recovery_rate == "n/a (no triggered timing faults)"
    assert isinstance(arm.cost_per_success, float)   # one real success

    failing = suite_b.run_configuration(
        task, "ungoverned", _manifests(task)[(task.id, "crash")], "crash",
        clean_state=clean)
    arm2 = suite_b.ArmReport(arm="ungoverned", outcomes=[failing])
    assert arm2.cost_per_success == "n/a (no completions)"


# -- full-suite shape: frontier + Thoth's expander --------------------------------

def test_frontier_report_and_thoth_expander():
    report = suite_b.run_suite(n_tasks=3, seed=SEED, k=1)
    d = report.to_dict()
    assert d["manifest_hash"] == report.manifest_hash
    assert report.drift_without_value_fault == 0     # Thoth: predicted 0
    assert d["thoth_expander"]["holds"] is True
    governed, ungoverned = report.arms["governed"], report.arms["ungoverned"]
    assert governed.drift_events == 0                # governance holds
    assert ungoverned.drift_events == 3              # one value fault per task
    assert governed.completion_rate < ungoverned.completion_rate
    assert isinstance(governed.cost_per_success, float)
    assert isinstance(ungoverned.cost_per_success, float)


def test_passk_reported_and_bounded():
    report = suite_b.run_suite(n_tasks=2, seed=SEED, k=3)
    for arm in report.arms.values():
        assert 0.0 <= arm.passk <= arm.pass1 <= 1.0
    assert "pass3" in report.arms["governed"].to_dict()
