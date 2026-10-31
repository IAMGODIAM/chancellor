# Chancellor

**The governance-and-eval harness for long-running agents.**

Built for the Meta Global AI Developer Hackathon (Cerebral Valley), Indie Dev track.
Built for the Meta Model API (Muse Spark · Muse Wonder · Muse Image · SAM 3.1).

> **Status — Oct 29, 2026:** fully offline today. The live transport is
> wired behind the client seam but not yet connected — live wiring is
> pending the team's API access. Everything below runs against offline
> stubs. See [BUILD-LOG.md](BUILD-LOG.md) for the current state.

> **Model-column errata:** `muse-wonder-full` is **not an API model** — it is a
> consumer subscription tier name, unreachable through the API. The frozen SPEC's
> tier list named it in error; the correction is recorded in [ERRATA.md](ERRATA.md)
> (the SPEC itself is frozen and is not edited). The authoritative model column —
> exact, versioned IDs only — lives in `src/chancellor/api_client.py` (`MODEL_IDS`).

## The pitch

Long-running agents fail quietly: they drift, mis-grade their own work, trust broken
tools, and sail past decisions that were never theirs to make. Frameworks optimize for
capability. Chancellor is the other half — **governance**:

- **Work is a graph, not a vibe.** Every run is an explicit, durable task graph that
  persists to disk and resumes after a crash.
- **Output is graded, not trusted.** Every consequential output is scored against a
  weighted rubric before acceptance.
- **Instruments fail closed.** If Chancellor's own checks error, the run halts. A broken
  gauge is a stop signal, never a pass — and there is no flag to turn this off.
- **Authority escalates; capability doesn't.** Spend, external sends, publishing,
  irreversible acts, and credential use stop at a human gate. Every gate decision —
  human or policy — leaves an append-only receipt.

Plus two eval suites: **Suite A**, normative judgment on synthetic remedy-design
problems, and **Suite B**, long-horizon agent reliability under failure injection.

## Results (measured, Oct 29, 2026)

**Suite B reliability frontier** — 360 runs, identical fault manifests (the
manifest hash `5c75a88c…` prints in every report):

| | Governed | Ungoverned |
|---|---|---|
| Drift (claimed success, final state failed) | **0** | **30** |
| Completion | 0.333 | 0.667 |
| Cost per success | $0.002147 | $0.001826 |

Governance is not free, and the price is printed, not hidden: the governed arm
completes fewer tasks at a higher cost per success — and never once claims a
success that did not happen. Drift 0 is an observation across these 360 runs,
stated with its denominator, not a bound on future runs.

**Tests:** 155 passing, 0 failing — including the kill-resume gate (SIGKILL
trials; each node's effect lands exactly once, asserted from the effect files
themselves): the kill-resume test passes 30/30 consecutive runs, and the full
suite is green on 3 consecutive runs.

**Suite A:** the calibration key of record is approved; the calibration run of
record has not yet run, and the zero-cost stand-in dry-runs failed the
calibration gate (κ 0.200 / 0.061, round 2 κ 0.314 / 0.132) — so no Suite A
score is reported yet. The gate catching an uncalibrated judge at $0 is the
method working as designed.

The full record — measurements, honest negative results, and corrections filed
as new entries rather than silent edits — is the development log:
[BUILD-LOG.md](BUILD-LOG.md) and [ERRATA.md](ERRATA.md).

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                 # smoke + unit tests (all offline)
chancellor demo            # the scripted governed run, offline
chancellor eval-a          # Suite A with stub agents
chancellor eval-b          # Suite B reliability metrics
```

Zero runtime dependencies — stdlib only, Python ≥ 3.11.

The demo writes its state to `./.chancellor` in the current directory
(task-graph state, the audit log, and its checkpoints), and re-runs
append to it. Delete `./.chancellor` for a clean run — the demo's printed
output is byte-identical across clean runs.

## Demo

<!-- FREEZE-DAY INSERT: replace the placeholder line below with the demo video URL. One line; nothing else in this section changes. -->

**Demo video:** _link lands here on submission day._

Until then, the demo is the offline run itself — `chancellor demo` (Quickstart
above). Its printed output is byte-identical across clean runs, so the video
is a capture of a fixed target, not a lucky take.

## Verify the audit log

Every governed run writes a hash-chained audit log with signed
checkpoints. Verify one offline — no credentials, no network:

```bash
python -m chancellor.verify_log .chancellor/audit-log.jsonl
```

Exit 0 means the chain is intact and the newest signed checkpoint
checks out. Exit 1 names the failure — a mid-log edit, a reordering, a
truncated tail, a forged checkpoint. A log with no checkpoint is never
reported as verified: tail truncation is undetectable without one, and
the verifier says so rather than guessing.

## Going live (when API access lands)

```bash
cp .env.example .env   # then fill in the values claimed at kickoff
export META_MODEL_API_BASE_URL=...   # from the Meta Model API console
export META_MODEL_API_KEY=...        # never commit this
```

Until credentials exist, `MetaModelClient.chat()` raises `NotConfiguredError`
unless given a transport — use `chancellor.api_client.offline_client()` for
development. The live transport lands when the team's API access does,
behind the same client seam; the build plan lives in the frozen SPEC.md
(available in the submission packet — it is not part of this repo).

## Layout

```
src/chancellor/
  task_graph.py    explicit DAG, validation, persistence, resume
  orchestrator.py  CrewRunner: governed execution of the graph
  grader.py        weighted rubrics, verdict bands, fail-closed grading
  instruments.py   pre-acceptance checks; errors == failures
  escalation.py    authority gates + append-only audit receipts
  api_client.py    Meta Model API client interface (env-configured)
  judge.py         the Judge: a separate caller that produces the scores
  receipts.py      hash-chained receipts + signed Merkle checkpoints
  verify_log.py    offline audit-log verifier (python -m chancellor.verify_log)
  cli.py           chancellor demo | eval-a | eval-b
  evals/
    suite_a.py           normative-judgment eval (remedy design)
    suite_a_bank.py      the 12 scenarios, 3 tiers, one-fact-flip twins
    suite_a_gold.py      sealed gold stakeholder lists (judge-side only)
    suite_a_probes.py    scorer probes: style twins, padding, order, hedging
    suite_a_references.py  the 36 hand-authored reference proposals
    suite_a_key.py       the calibration key of record (approved)
    calibration.py       agreement statistics (κ, ρ, MAE) + the gate
    suite_b.py           long-horizon reliability eval (failure injection)
    suite_b_tasks.py     the 10 world-state tasks Suite B executes
    suite_b_world.py     the assertable world state the tasks run over
tests/             smoke + unit tests, all offline
```

## How it maps to the judging criteria

- **Impact (30%)** — for anyone who runs long-running agents with real
  authority: every consequential act is gated before it happens, graded after
  it lands, and receipted either way — so an operator can hand an agent real
  work (spend, sends, publishing, irreversible acts) and prove afterward
  exactly what it did, what it cost, and who approved it.
- **Tooling — creative use of Meta's tools (25%)** — governance as the
  product, built for the Meta Model API's model column (Spark, Wonder, Image,
  SAM 3.1 — exact, versioned IDs only; see [ERRATA.md](ERRATA.md) E-1):
  fail-closed instruments and receipt-bearing gates are the idea, not a
  feature list.
- **Demo (25%)** — `chancellor demo` runs end-to-end offline today; the same run
  goes live on Meta models once API access lands, behind a one-function
  transport swap. (Video: see the Demo section above.)
- **Technical Depth (20%)** — durable resumable task graphs proven under
  SIGKILL trials, rubric-graded outputs from an independent judge,
  failure-injected reliability measurement with the cost printed beside the
  frontier, and a hash-chained audit log verifiable offline.

## Agent collaboration

The [Chancellor agent bridge](docs/bridge/README.md) connects bounded work, evidence and handoffs. The [opening war room](https://github.com/IAMGODIAM/chancellor/issues/1) contains Wabi’s analysis and pending peer invitations; it is asynchronous, not a claim of live-bus connectivity or consensus.
