# RUN-7 — Verified Results (collection + independent verification)

**Run:** RUN-7, the Chancellor 10x evidence run — RUN-5 program repeated at 10x volume on the frozen tree `31ea039e5312d93cc8df6b59465eec3191dbcb66`, ten Lambda `gpu_1x_a10` boxes `chancellor-run7-b0..b9`. Authority: `RUN-CARD.md` + `LAUNCH-REPORT.md` in this folder.

**Verdict: PASS — every figure below was recounted from the raw collected outputs; governed drift is 0 everywhere it was measured, and the ungoverned control drifted exactly as designed.**

Collection ran 2026-11-02 05:26–05:39 UTC. All ten boxes were found DONE (`progress.json` phase DONE, `pass_all=True`, `results/ALL-DONE` present; program-complete times 04:00–04:38 UTC, ahead of the card's 04:35–05:15 expectation) — no box was mid-stage, so no partial collection and no wait-and-recheck were needed. Each box's `results/`, `soaks/` (including every `audit.jsonl.checkpoints.jsonl` sidecar — the files RUN-5 missed — plus all per-segment state files), `beacon.log`, `driver.out`, `progress.json` and `logs/` were tarred on-box, sha256-recorded on-box, pulled with `jfile.py`, and the local sha256 matched the on-box sha256 for all ten tarballs before extraction into `results/box<i>/`. Per box: 3,880 files in `results/`+`soaks/` (3,889 files pulled in total) — identical counts on all ten boxes. All ten instances were terminated 05:39–05:41 UTC, ~80 minutes ahead of their 06:59–07:01 UTC cap-watch deadlines, and a post-termination instance list confirms none of the ten remains; the only active box left is `chancellor-run8-tier1`, which this run did not touch. `DONE` is touched in this folder.

Estimated spend: ~$12.46–12.50 per box, ~$124.77 total (launch epoch = cap deadline − 11 h, termination 05:40 UTC, $1.29/hr) — inside the $15/box cap and the $141.90 all-to-deadline ceiling. It lands above the card's $112–116 prompt-collection projection because the boxes idled in DONE state while collection and the full independent verification ran before termination (the card's order: terminate only after the pull verifies; verification was completed pre-termination so any gap could still have been re-pulled).

## Method (what "independent" means here)

- **Lane 1 — independent recount (primary).** A purpose-built parser (`results/verify_run7.py`, output `results/verification-data.json`) that imports no product code: it re-sums Suite B drift from the `per_seed` and `cells` records (not the stage headers — headers were then compared against the recount), re-counts T3 gates from `per_gate`, regenerates each soak's seeded fault plan, re-derives soak drift from the persisted per-segment state files using the soak program's own published definitions (payload checksum scan + clean-reference final value), recounts corrupted state files by re-hashing all 19,200 state files against their `.sha256` sidecars, and re-walks every audit chain (seq, prev-hash linkage, entry-hash recomputation over canonical JSON) plus every checkpoint envelope in every sidecar (log_size progression, head hash, Merkle root recomputed). **Result: zero anomalies — every recount matched every summary it was checked against.**
- **Lane 2 — product-verifier cross-check.** The frozen tree's own `chancellor.verify_log` was run offline over all 40 collected audit logs with their checkpoint sidecars (this lane also validates the checkpoint HMAC signatures): **40/40 logs verify OK, 18,403 entries, 2,320 checkpoints, zero failures** (`results/product-verifier-crosscheck.json`) — identical totals to Lane 1.
- Bounds use the exact zero-event 95% upper bound `1 − 0.05^(1/n)`; the rule-of-three figure `3/n` is printed beside it.

## S1 — Suite B (pooled recount, raw source: `results/box<i>/results/stage1_suite_b.json` on all ten boxes)

- **Volume:** 56,000 runs recounted — Part A 36,000 (3,600/box) + Part B 20,000 (2,000/box) — matching the card's pooled target exactly. Seed lists on every box match `run_card.json` (Part A bases 20271030 + (i+1)·10000, Part B bases 31000 + (i+1)·1000).
- **Part A governed drift: 0** of 18,000 governed runs pooled (1,800/arm/box; per-seed recount, all 300 seed records). **Ungoverned drift: 3000** of 18,000 on identical fault manifests (exactly 300 on every box) — the control arm drifted at 16.67%, the governed arm at 0. `drift_without_value_fault` recount: 0 pooled.
- **Part A bounds (governed zero):** pooled per-arm n=18,000 → 95% UB **0.0166%** (rule of three 0.0167%). Per-box per-arm n=1,800 → 0.166% (0.167%). Manifest level at the denominator named in the collection brief, n=100 → **2.95%** (3.00%). Measured directly from the raw files: 300 per-seed suite-manifest records carrying 270 distinct `manifest_hash` values pooled (29–30 distinct per box; hashes repeat across some seeds, i.e. those seeds share identical manifest content) with governed drift 0 in all of them → bound at distinct-manifest n=270 is 1.10% (1.11%), at manifest-instance n=300 is 0.99% (1.00%). All four denominators are printed; none is hidden.
- **Part B (value-cell extension, governed-only by design): drift 0 in all 200 cell instances** (20 named cells × 10 boxes, each cell instance n=100 runs on 100 distinct seeds; recount from the `cells` records: 20000 runs, drift 0). Per-cell-instance bound (n=100): **2.95%**. Each of the 20 named cells pooled across boxes (n=1,000): drift 0, bound 0.299%. Extension pooled (n=20,000): drift 0, bound 0.0150% (0.015%). **Successes claimed under value faults: 0 in every cell** (recounted `successes` sum = 0 pooled) — Part B's zero leans on Part A's paired governed/ungoverned control and is reported that way.

## S2 — T3 (raw source: `results/box<i>/results/stage2_t3.json`)

- **3000 of 3000 gates passed, 0 failed** — recounted from the 3,000 `per_gate` records (rc=0 and "2 passed" tail on every gate), 60000 trials total. Per box: 300/300 on all ten boxes.
- **Label (pre-registered, mandatory):** this is **3,000 gates as a 10-box reproduction of the same 300-gate instrument — NOT 3,000 independent trials** (`stage_t3.py` takes no seed parameter and ran unchanged on all ten boxes).

## S3 — Soaks (raw sources: `results/box<i>/soaks/soak-<seed>/` — `summary.json`, `audit.jsonl`, `audit.jsonl.checkpoints.jsonl`, `checkpoint.json`, `kills.json`, `supervisor.json`, `SOAK-DONE.json`, `state/`)

- **40 of 40 soaks pass.** Segments: **19200 of 19200** (480/480 on every soak), 230400 steps. Segments complete 17,661 / halted 1,539 pooled — the complete/halted split was independently recounted from the persisted state files (all 12 nodes done = complete) and matches every soak's summary exactly. Halted segments are the fail-closed signature under injected faults.
- **Faults injected: 1920** (48 per soak) — matches the independently regenerated seeded fault plans (one fault every 10 segments) exactly.
- **Drift: 0** — summary-accounted 0 on all 40 soaks AND independently re-derived 0 from the 19,200 persisted state files (checksum scan + reference-final comparison, fault-plan aware). **Corrupted state files: 0** — recounted by re-hashing all 19,200 `seg-*.json` files against their sidecars (every soak holds the full 480 json + 480 sha256 files; none missing, none mismatched).
- **Chains: 18403 audit entries across 40 logs, zero breaks** — Lane 1 found 0 seq mismatches, 0 prev-hash breaks, 0 entry-hash mismatches, 0 duplicate entry hashes. **Checkpoint sidecars (the RUN-5 gap, collected explicitly this run):** 40 sidecar files holding 2,320 envelopes (58 per soak); for every envelope, log_size progression is monotonic and its head hash and Merkle root match Lane 1's recomputation over the collected entries; every final checkpoint's log_size equals its log's entry count. Lane 2 (product verifier, signatures included) agrees: 40/40 OK.
- **Kills / verifications:** exactly 1 supervisor SIGKILL per soak (40 total, `kills.json`), every `SOAK-DONE.json` rc=0; 57 periodic in-run chain verifications per soak (2,280 total), all ok with empty failure lists. `stage3_soaks.json` and the soak entries inside `SUMMARY.json` match the per-soak `summary.json` files on every checked field, on all ten boxes.

## Per-box record

| Box | Instance | Region | Program complete (UTC) | Part A gov / ungov drift | Part B drift | T3 | Soaks pass | Tarball sha256 (pull-verified) |
|---|---|---|---|---|---|---|---|---|
| 0 | `404d4e9a143645c2a2ac64203e1e1b51` | us-east-1 | 2026-11-02 04:00 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `9ac9a6013465dc4b…` |
| 1 | `41153673ed2c4d47abde32e36ceac4ea` | us-east-1 | 2026-11-02 04:08 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `011caf46e4d3ba65…` |
| 2 | `9162c2f4a14546128d4eac809f705526` | us-east-1 | 2026-11-02 04:17 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `027378085d81ecba…` |
| 3 | `08976b202fe04435ba510cbecdd3ccf0` | us-east-1 | 2026-11-02 04:17 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `6621685964bb500a…` |
| 4 | `eb54a637cc864b75a1b5ad802186e2e6` | us-east-1 | 2026-11-02 04:22 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `717028348b56a0d6…` |
| 5 | `1d45f8b59b3e463c9f3a2c3f1646804b` | us-west-1 | 2026-11-02 04:28 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `856130aad12dc2ef…` |
| 6 | `e70b47e182e74bd7a782311e460ccc43` | us-west-1 | 2026-11-02 04:28 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `2566504e6ffcbe52…` |
| 7 | `480c86fe6daa42428fad34fdc8d49b2f` | us-west-1 | 2026-11-02 04:29 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `50639f185006b662…` |
| 8 | `4248fbaa0ec04c399620adc33b71bbbd` | us-west-1 | 2026-11-02 04:33 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `3d9897101fb8fe0b…` |
| 9 | `568aa01949a443309632cb4d8c5e5bb7` | us-west-1 | 2026-11-02 04:38 | 0 / 300 of 1,800/arm | 0 of 2,000 | 300/300 | 4/4 | `e76ded3eea32820f…` |

Full per-file sha256 for every stage file and per-soak summary/audit/sidecar: `results/sha256-manifest.json`. Per-soak detail (entries, complete/halted, checkpoints, state-file counts): `results/verification-data.json`.

## Per-soak record

| Box | Soak seed | Chain entries | Checkpoints | Complete / halted | Drift (recount) | Corrupt (recount) | Kills |
|---|---|---|---|---|---|---|---|
| 0 | 4301 | 456 | 58 | 438 / 42 | 0 | 0 | 1 |
| 0 | 4302 | 459 | 58 | 439 / 41 | 0 | 0 | 1 |
| 0 | 4303 | 462 | 58 | 440 / 40 | 0 | 0 | 1 |
| 0 | 4304 | 462 | 58 | 443 / 37 | 0 | 0 | 1 |
| 1 | 4305 | 462 | 58 | 443 / 37 | 0 | 0 | 1 |
| 1 | 4306 | 459 | 58 | 440 / 40 | 0 | 0 | 1 |
| 1 | 4307 | 462 | 58 | 438 / 42 | 0 | 0 | 1 |
| 1 | 4308 | 463 | 58 | 439 / 41 | 0 | 0 | 1 |
| 2 | 4309 | 464 | 58 | 443 / 37 | 0 | 0 | 1 |
| 2 | 4310 | 459 | 58 | 442 / 38 | 0 | 0 | 1 |
| 2 | 4311 | 460 | 58 | 440 / 40 | 0 | 0 | 1 |
| 2 | 4312 | 457 | 58 | 441 / 39 | 0 | 0 | 1 |
| 3 | 4313 | 459 | 58 | 442 / 38 | 0 | 0 | 1 |
| 3 | 4314 | 462 | 58 | 442 / 38 | 0 | 0 | 1 |
| 3 | 4315 | 462 | 58 | 441 / 39 | 0 | 0 | 1 |
| 3 | 4316 | 463 | 58 | 441 / 39 | 0 | 0 | 1 |
| 4 | 4317 | 459 | 58 | 443 / 37 | 0 | 0 | 1 |
| 4 | 4318 | 453 | 58 | 441 / 39 | 0 | 0 | 1 |
| 4 | 4319 | 452 | 58 | 441 / 39 | 0 | 0 | 1 |
| 4 | 4320 | 464 | 58 | 444 / 36 | 0 | 0 | 1 |
| 5 | 4321 | 460 | 58 | 441 / 39 | 0 | 0 | 1 |
| 5 | 4322 | 458 | 58 | 442 / 38 | 0 | 0 | 1 |
| 5 | 4323 | 458 | 58 | 443 / 37 | 0 | 0 | 1 |
| 5 | 4324 | 469 | 58 | 448 / 32 | 0 | 0 | 1 |
| 6 | 4325 | 461 | 58 | 441 / 39 | 0 | 0 | 1 |
| 6 | 4326 | 464 | 58 | 439 / 41 | 0 | 0 | 1 |
| 6 | 4327 | 458 | 58 | 439 / 41 | 0 | 0 | 1 |
| 6 | 4328 | 466 | 58 | 442 / 38 | 0 | 0 | 1 |
| 7 | 4329 | 462 | 58 | 442 / 38 | 0 | 0 | 1 |
| 7 | 4330 | 459 | 58 | 441 / 39 | 0 | 0 | 1 |
| 7 | 4331 | 462 | 58 | 441 / 39 | 0 | 0 | 1 |
| 7 | 4332 | 455 | 58 | 440 / 40 | 0 | 0 | 1 |
| 8 | 4333 | 456 | 58 | 442 / 38 | 0 | 0 | 1 |
| 8 | 4334 | 460 | 58 | 444 / 36 | 0 | 0 | 1 |
| 8 | 4335 | 462 | 58 | 442 / 38 | 0 | 0 | 1 |
| 8 | 4336 | 462 | 58 | 443 / 37 | 0 | 0 | 1 |
| 9 | 4337 | 460 | 58 | 441 / 39 | 0 | 0 | 1 |
| 9 | 4338 | 458 | 58 | 444 / 36 | 0 | 0 | 1 |
| 9 | 4339 | 458 | 58 | 440 / 40 | 0 | 0 | 1 |
| 9 | 4340 | 456 | 58 | 445 / 35 | 0 | 0 | 1 |

## Scope and limits

- Suite B figures are recounts of the stage records' own per-seed/per-cell detail (the deepest raw layer the program writes), cross-checked against the stage headers, `SUMMARY.json`, and the run card's seed map — the same evidence depth as RUN-5, with the addition that soak drift and corruption, summary-accounted in RUN-5, are here fully re-derived from collected state files and checkpoint sidecars.
- Checkpoint signatures rest on the tree's dev HMAC signer (a well-known demo secret in the frozen code, by its own docstring) — they are consistency evidence, not non-repudiation, and are reported that way.
- No README, portal packet, or public surface was amended in this run, per instructions; the re-render is a separate desk step after this verification. RUN-8's box, the judging soak, and the repos were not touched (repos were read only, to obtain the chain/checksum definitions).

Bounds table (exact 95% UB / rule-of-three): n=100 → 2.9513% / 3.0%; n=270 → 1.1034% / 1.11111%; n=300 → 0.99361% / 1.0%; n=1,000 → 0.29912% / 0.3%; n=1,800 → 0.16629% / 0.16667%; n=18,000 → 0.01664% / 0.01667%; n=20,000 → 0.01498% / 0.015%.
