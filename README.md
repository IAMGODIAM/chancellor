# Warden

**The governance-and-eval harness for long-running agents.**

Built for the Meta Global AI Developer Hackathon (Cerebral Valley), Indie Dev track.
Runs on the Meta Model API (Muse Spark · Muse Wonder · Muse Image · SAM 3.1).

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

## Going live (hackathon kickoff, Oct 26)

```bash
cp .env.example .env   # then fill in the values claimed at kickoff
export META_MODEL_API_BASE_URL=...   # from the Meta Model API console
export META_MODEL_API_KEY=...        # never commit this
```

Until credentials exist, `MetaModelClient.chat()` raises `NotConfiguredError`
unless given a transport — use `warden.api_client.offline_client()` for
development. The live transport lands on Day 1 of the build plan (see the
frozen SPEC.md in the parent folder).

## Layout

```
src/warden/
  task_graph.py    explicit DAG, validation, persistence, resume
  orchestrator.py  CrewRunner: governed execution of the graph
  grader.py        weighted rubrics, verdict bands, fail-closed grading
  instruments.py   pre-acceptance checks; errors == failures
  escalation.py    authority gates + append-only audit receipts
  api_client.py    Meta Model API client interface (env-configured)
  evals/suite_a.py normative-judgment eval (remedy design)
  evals/suite_b.py long-horizon reliability eval (failure injection)
  cli.py           warden demo | eval-a | eval-b
tests/             smoke + unit tests, all offline
```

## How it maps to the judging criteria

- **Creativity** — governance as the product: fail-closed instruments and
  receipt-bearing gates are the idea, not a feature list.
- **Technical ambition** — durable resumable graphs, rubric-graded outputs,
  failure-injected reliability measurement, cost as a first-class instrument.
- **Whether it works** — `warden demo` runs end-to-end offline today; the same
  run goes live on Meta models at kickoff with a one-function transport swap.
