# Warden

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
> exact, versioned IDs only — lives in `src/warden/api_client.py` (`MODEL_IDS`).

## The pitch

Long-running agents fail quietly: they drift, mis-grade their own work, trust broken
tools, and sail past decisions that were never theirs to make. Frameworks optimize for
capability. Warden is the other half — **governance**:

- **Work is a graph, not a vibe.** Every run is an explicit, durable task graph that
  persists to disk and resumes after a crash.
- **Output is graded, not trusted.** Every consequential output is scored against a
  weighted rubric before acceptance.
- **Instruments fail closed.** If Warden's own checks error, the run halts. A broken
  gauge is a stop signal, never a pass — and there is no flag to turn this off.
- **Authority escalates; capability doesn't.** Spend, external sends, publishing,
  irreversible acts, and credential use stop at a human gate. Every gate decision —
  human or policy — leaves an append-only receipt.

Plus two eval suites: **Suite A**, normative judgment on synthetic remedy-design
problems, and **Suite B**, long-horizon agent reliability under failure injection.

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

pytest                 # smoke + unit tests (all offline)
warden demo            # the scripted governed run, offline
warden eval-a          # Suite A with stub agents
warden eval-b          # Suite B reliability metrics
```

Zero runtime dependencies — stdlib only, Python ≥ 3.11.

The demo writes its state to `./.warden` in the current directory
(task-graph state, the audit log, and its checkpoints), and re-runs
append to it. Delete `./.warden` for a clean run — the demo's printed
output is byte-identical across clean runs.

## Verify the audit log

Every governed run writes a hash-chained audit log with signed
checkpoints. Verify one offline — no credentials, no network:

```bash
python -m warden.verify_log .warden/audit-log.jsonl
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
unless given a transport — use `warden.api_client.offline_client()` for
development. The live transport lands when the team's API access does,
behind the same client seam; the build plan lives in the frozen SPEC.md
(available in the submission packet — it is not part of this repo).

## Layout

```
src/warden/
  task_graph.py    explicit DAG, validation, persistence, resume
  orchestrator.py  CrewRunner: governed execution of the graph
  grader.py        weighted rubrics, verdict bands, fail-closed grading
  instruments.py   pre-acceptance checks; errors == failures
  escalation.py    authority gates + append-only audit receipts
  api_client.py    Meta Model API client interface (env-configured)
  judge.py         the Judge: a separate caller that produces the scores
  receipts.py      hash-chained receipts + signed Merkle checkpoints
  verify_log.py    offline audit-log verifier (python -m warden.verify_log)
  cli.py           warden demo | eval-a | eval-b
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

- **Creativity** — governance as the product: fail-closed instruments and
  receipt-bearing gates are the idea, not a feature list.
- **Technical ambition** — durable resumable graphs, rubric-graded outputs,
  failure-injected reliability measurement, cost as a first-class instrument.
- **Whether it works** — `warden demo` runs end-to-end offline today; the same
  run goes live on Meta models once API access lands, behind a one-function
  transport swap.
