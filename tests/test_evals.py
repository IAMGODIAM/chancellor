from warden.evals import suite_a, suite_b


def test_suite_a_structure():
    report = suite_a.run_suite()
    assert len(report.results) == len(suite_a.SCENARIOS)
    assert 0 <= report.mean_total <= 100
    assert 0.0 <= report.pass_rate <= 1.0
    d = report.to_dict()
    assert d["suite"] == "A-normative-judgment"


def test_suite_b_metrics_and_determinism():
    # Stage W4: the coin-flip simulator is deleted (AM-12c). Suite B now
    # runs real CrewRunner tasks under a deterministic fault manifest;
    # same seed -> same manifest -> byte-identical frontier report.
    r1 = suite_b.run_suite(n_tasks=3, seed=42, k=1)
    r2 = suite_b.run_suite(n_tasks=3, seed=42, k=1)
    assert r1.to_dict() == r2.to_dict()
    assert 0.0 <= r1.completion_rate <= 1.0
    assert isinstance(r1.recovery_rate, float) and 0.0 <= r1.recovery_rate <= 1.0
    assert isinstance(r1.cost_per_success, float) and r1.cost_per_success > 0.0
    assert r1.total_drift == 0          # governed arm holds the line


def test_suite_b_no_failures_reports_na_not_vacuous_perfection():
    # Red-team K5 / Lane 1 handoff: with zero triggered faults the old
    # suite reported recovery_rate == 1.0 — vacuous perfection. The
    # rebuilt suite reports "n/a (no triggered faults)" instead.
    from warden.evals.suite_b_tasks import TASKS
    task = TASKS[0]
    clean_run = suite_b.run_configuration(task, "governed", [], "clean")
    arm = suite_b.ArmReport(arm="governed", outcomes=[clean_run])
    assert clean_run.success
    assert arm.recovery_rate == "n/a (no triggered faults)"
    assert arm.drift_events == 0
