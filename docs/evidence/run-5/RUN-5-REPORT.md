# RUN-5 — the extensive test on the finalized tree

**Tree:** `31ea039` (the code-beauty canon complete; 186 tests, lint and types clean).
**Where:** one Lambda H100 instance, 2026-10-31; program wall-clock 7.89 h.
**Verdict: PASS — every pre-registered success criterion met.**
Raw records: the four JSON files beside this report (sha256 in the build log entry
and in the run's completion record).

## S1 — Suite B at 10x (5,600 runs)

Part A (3,600 runs, 30 seeds): governed drift **0 / 1,800** against ungoverned drift
**300 / 1,800** on identical fault manifests — the Oct 30 frontier, replicated on the
finalized tree. The zero travels with its bounds: a 95% upper bound of **0.166%** at
the cell level (n = 1,800), and the weaker manifest-level bound of **25.9%**
(0 of 10 manifests).

Part B (value-cell extension, 2,000 runs, 20 cells): governed drift **0 in all
20 cells** — 0 completions claimed under value faults. Part B is governed-only by
design; its zero leans on Part A's paired control. Per-cell bound **2.95%**
(n = 100 per cell); the pooled bound (0.1497%, n = 2,000) describes the extension as
a whole and is never attached to an individual cell.

## S2 — Crash-atomicity (T3 v2, ×300)

**300 / 300 gates passed, 0 failed — 6,000 trials.** The harness defect behind the
earlier 290/300 readings (a non-atomic write in the *test harness*, never in
Chancellor's own state handling) stays fixed at full count on the final tree.

## S3 — Endurance: four parallel 8-hour soaks

Each soak (seeds 4101–4104): **480 / 480 segments**, 5,760 steps, **drift 0**,
48 injected faults, **0 corrupted state files**, and a final hash chain whose
entry links verify in full from the collected chains (460–462 entries per
chain; the signed-checkpoint portion of the on-box verification rests on the
soak's own recorded result — the checkpoint sidecars were not collected, a gap
the red team flagged on the record). Segments that met a fault halted — the
fail-closed signature; a halted segment is terminal and the soak proceeds —
and every soak still finished all 480.

## Verification discipline

An independent red team audited this run in two phases, both
PASS-WITH-RESIDUALS with every residual a phrasing or evidence-scope obligation,
discharged on the record. Phase 1 re-derived the S1 numbers and bounds from the
stage record. Phase 2 re-derived the four soak chains from the raw audit files —
1,846 entries, every seq, link, and hash intact — and cross-checked the recorded
aggregates against the per-soak summaries: drift is *summary-accounted* (the
per-segment state files were not collected, so drift is not independently
re-derivable from the chains), and the audit says so wherever it matters.
Collection was performed twice, independently, with identical sha256 hashes.
Drift is a bound with its denominator, never a bare zero — here as everywhere
in this project.
