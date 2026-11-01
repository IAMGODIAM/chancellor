# Glossary

The code cites the build's governing documents inline — amendment codes
(AM-n, EA-n) and a small working vocabulary. This file is the key. The
amendments themselves live in the build protocol; each entry below gives
the operative meaning where the code relies on it.

## The measures (Suite B)

- **Drift** — a run claims completion AND its final state fails the
  task's final check (the test the task itself defines for "the work
  is actually done"). The pre-registered primary metric of Suite B.
- **Divergence** — a claimed run's final state differs from the clean
  reference state, whether or not the predicate catches it.
- **Displacement** — a fault outcome scores materially below the clean
  outcome: the work was not merely damaged, it was replaced by lesser
  work.
- **Manifest** — the deterministic fault list a governed run is bound
  to, identified by its content hash (`manifest_hash_of`). Nothing
  outside the manifest is comparable across runs.

## Amendment codes cited in the code

- **AM-2** — Effect axes. A gated action carries every axis it truly
  has (send, spend, publish, …); the escalation gate fires if ANY axis
  is present, and the receipt records the axes.
- **AM-3** — Fault classes: crash / omission / value (timing counts as
  omission). Recovery is measured only over the faults that actually
  fired — a fault that never triggered is not in the denominator.
- **AM-4** — Three names, three measures: drift, divergence,
  displacement (above). Never report one under another's name.
- **AM-5** — Model column discipline: only exact, versioned model IDs
  in any reported run. `muse-spark-1.3` is the Suite B worker;
  `muse-wonder-1.0` is the judge.
- **AM-7iii** — Who sees what while scoring: the blind Suite A scorer
  reads the proposal — and, for the stakeholder criterion, the sealed
  list of parties the scenario actually affects — but never the
  scenario's scoring key.
- **AM-9v** — Transport-reported `cost_usd` is advisory only; costs of
  record come from the transport meter, priced at list rates.
- **AM-9vi** — Spend lanes: `canonical` (counts against the reported
  ceiling), `contributor`, `nvidia` (dev/overflow), `fake` (offline).
- **AM-10iii** — Fail-closed at the source: an approver that cannot be
  reached denies; it never abstains into approval.
- **AM-10v** — Record-or-halt: an approval that exists but is not
  recorded does not release the action.
- **AM-12c** — No loaded dice: randomness that is not seeded and stated
  is deleted, not kept.
- **AM-12d** — Narrow claim: Suite B's results describe this runner,
  its harness, and this manifest — nothing wider.
- **EA-5** — Executive amendment on spend: $40 planning target, $60
  hard stop for the Meta credit envelope of the reported runs.

## Working vocabulary

- **Gate** — a point where an action may not proceed without a recorded
  approval at the authority its effect axes demand.
- **Receipt** — the sealed, hash-chained record of a decision and its
  approval trail; the unit the verifier checks.
- **Checkpoint** — a signed digest over a prefix of the receipt chain,
  so verification need not trust the log's tail.
- **Sealed** — written before the outcome it describes exists (a
  prediction, a scoring key, a fault manifest), and never edited after.
- **Lane** — a named route for work or spend, with its own accounting.
- **Suite A** — the grading-calibration eval: 12 scenarios × 3 quality
  tiers against an approved key, gated on self-agreement (κ ≥ 0.7).
- **Suite B** — the fault-injection eval: scripted agents under a
  governed and an ungoverned arm, measured on the AM-4 measures.
- **T3** — the kill-resume gate: a worker is SIGKILLed mid-step and the
  graph must resume with no duplicated or lost effect.
