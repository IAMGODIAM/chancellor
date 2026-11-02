# INSTALL HEARING — RUN CARD (frozen before L1)

The pre-registered proof run for governed capability install
(SPEC-FOUNDRY-CHANCELLOR §3, ratified 2026-11-02). This card is
frozen before any leg runs; the legs below execute exactly as
written, and the claims F1–F8 are scored by the instruments named
in the spec. A failed claim is reported as failed.

## Perimeter (pinned)

Phase 0 — the Atlas layer, doc-only skill bundles, effect class R,
∅ cost surfaces, ∅ external surfaces, ∅ standing triggers. The
Phase-1 kinds (connector, schedule), executable payloads, and the
Prometheus layer are out of scope by construction.

## State the run runs against (FB3 route, named per spec)

A **sandboxed copy of the Foundry manager state** at
`~/workspace/hackathon-2026/scratch/foundry-build/sandbox-home/`
(the Foundry lane is live in the real state dir; the hearing does
not write to it). Manager invocations run with `HOME` pointed at
the sandbox and `FOUNDRY_SCOPE_PATH` at the hearing scope
artifact. The sandbox's skills root is a symlink to the real
library, so installs land in the real catalog under the hearing's
two bundle ids only — Beat 1 / Beat 2 discovery evidence is
genuine — and enforcement moves trees out again. The live Foundry
registry is never written by this run. Sandbox registry copy at
freeze: sha256 `303f64a8a2a476b085ac952df999bc3b14746a6b2db8c4d3be7c398cac7dd26a`
(21 events, head `a7d07010be7102ed5b5686a3203f39bf56686dfb1944a9f440bcd5fc2daf5a56`
— the Phase 0 + Phase 1 history the hearing inherits).

## Frozen artifacts

- **Scope artifact:** `foundry-install-hearing-scope`
  (sandbox `foundry/scope/hearing-scope.json`); file sha256
  `de2d160329059b88b1cdbff4dfb3f54ad046232f62202db95f3ed1d506cdde1f`,
  canonical sha256
  `9a64918862efa7b3d312106ee4a87c0630232c26bfc9db8ddd19102c056ee45f`.
  Enumerates exactly: bundles `local-install-hearing`,
  `local-install-hearing-probation`; acts {install, rollback,
  deprecate}; ∅ elsewhere.
- **Commission (Step 0):** minted on the live issuer before any
  act, citing the Chairman's ratification of the spec (RECORD.md,
  2026-11-02) and his build word. Receipt
  `b83be417a927f67c514116619f8d093439e02d46b17777c0bca11719cc5adec1`,
  issuer log index **22** — strictly pre-dating every act.
- **Bundle A** `local-install-hearing` — pin
  `sha256:580eb8c0279570456266d755a106a8cbe8390c50bd9eb63825d47828f1edbd31`.
- **Bundle B** `local-install-hearing-probation` — pin
  `sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6`.
- **Grader of record:** the deterministic rubric function
  `grader.py` (sha256
  `4e41c99e7da249366b8e84615be85a31695d62de15b2d500d03d49ae92290af9`),
  implementing bundle B's filed rubric mechanically. Dry-graded
  before the run (§3.4(iii)): PASS on the correct exercise, FAIL on
  the prescribed misuse.
- **Approver of record:** the hearing director (the Atlas build
  lane), deciding per this card's frozen leg script under the
  Chairman's ratification + build word: the L3 presentation is
  DECLINED by script; every other gate presentation in the legs is
  approved. The machinery under test is the gate's receipting, not
  the director's discretion — stated plainly, as Phase 0 stated its
  standing commission.
- **Beat-2 verifiers:** fresh subagent contexts that installed
  nothing (one per bundle), briefed read-only apart from their
  report + exercise artifact.
- **Independent scorer:** a fresh subagent context, post-run,
  running the cold verifiers + an independent fold over the exports
  (F5/F7) and reporting disagreements, if any.

## Named readings (stated before the legs, not after)

1. **L7 rollback mechanics.** The manager's CLI rollback verb
   executes update acts; for an install act it refuses at the verb
   gate, naming the semantics itself: an install-act rollback onto
   an ABSENT snapshot "is the same restore path with an empty file
   set" (DESIGN-SPEC §4.5 covers ABSENT snapshots). L7 therefore
   executes through the manager's own §4.5 primitives
   (`verify_snapshot` → `restore_from_snapshot` → compensating
   registry event → the remove/install receipt pair), composed by
   the governor under the Step-8 gate.
2. **Act-record citation.** The manager composes act records
   itself (their citation block cites the commission receipt). The
   Chancellor decision citation is carried in the act journal as a
   governor-filed artifact (`chancellor-decision.json`) — the
   journal is the act's record surface (Phase 0 precedent:
   operator-filed Beat 1 / Beat 2 artifacts) — and the Chancellor
   chain closes the correspondence from its side. The bridge audit
   checks correspondence only.
3. **L7's end-state vocabulary.** After the rollback, the tree is
   ABSENT from the library; the registry fold carries the bundle as
   DEPRECATED (its binding history is append-only) — q4's answer is
   the operative liveness fact and is reported verbatim.

## Legs (execute in order; §3.2)

- **L1** Proposal + pre-flight PASS, bundle A.
- **L2a** Payload altered after staging → refusal
  `install-pin-mismatch`, zero payload moved (A re-staged clean
  after).
- **L2b** Out-of-scope bundle id → refusal `install-out-of-scope`,
  witnessed from the Chancellor side (no Foundry record, by design).
- **L3** Approver declines a clean in-scope proposal for A →
  `approver-declined` Decision; registry/library diff proves
  nothing installed.
- **L4** Third proposal approved → manager installs under the
  decision's citation → Beat 1 PASS. State:
  **installed-unverified**.
- **L5** Beat 2 by a fresh verifier → `capability_probation_opened`
  with all Step-6 fields.
- **L6** Ten receipted uses of A (≥1 graded PASS) →
  `capability_probation_closed`, standing earned.
- **L7** Governed rollback of A to the pre-install ABSENT snapshot:
  snapshot integrity verified first; tree ABSENT verified;
  compensating pair receipted in both chains; effects reconciled
  (the live window named, residual-accepted per G-3.3 — honestly
  vacuous beyond it for a doc-only bundle).
- **L8** Bundle B through the full arc → probation opens → misuse
  use graded FAIL (strike 1 receipted) → a further receipted use,
  no suspension at one strike → second misuse graded FAIL →
  suspension in one motion (suspension entry + disable enforcement
  with discovery at 0 hits + escalation Decision). **B is left
  suspended at run end.**

## Claims

F1–F8 exactly as pre-registered in SPEC-FOUNDRY-CHANCELLOR §3.3 —
fact, instrument, threshold — scored in VERIFIED-RESULTS.md from
the exports filed beside this card. PASS licenses exactly the
Stage B packet sentence (grade clause included) and nothing beyond
it: not Phase-1 kinds, not executables, not cost-bearing bundles,
not the Prometheus layer.
