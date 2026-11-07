# Capability install — a governed act class

**Status: SHIPPED on this tree.** This document is the public form
of the specification the build was executed against. The behavior
it describes is in this tree: the ninth act class in
`src/chancellor/escalation.py`, the governor in
`src/chancellor/installs.py`, frame v2 in
`docs/governance-frame.md`, and the pre-registered proof in
`docs/evidence/foundry-install-hearing/`. Where this document and
the code disagree, the code and the evidence file govern.

**Provenance.** Chancellor's governance frame grew a sixth clause
because a working system in the entrant's wider multi-agent
programme — the Foundry, a governed capability pipeline whose
doc-only perimeter is admitted on measured evidence — already ran
the install machinery this act class governs: proposal, pre-flight
checks before anything moves, a signed registry, receipted acts,
and rollback to a verified snapshot. The bridge built here lets
Chancellor's decision chain govern that machinery act by act. No
external code is reused; the composition is Chancellor's own.

## 1. The gap

The frame's eight act classes govern what an agent does with the
world — read, draft, compute, spend, send, publish, the
irreversible, the credential-bearing. None of them governs what an
agent does to *itself*: gaining a new capability. Self-modification
was the one consequential act with no class, no gate, and no
receipt. Frame v2 closes that gap two ways: clause 2 now names an
act as gated when it can "change what the agent itself can do,"
and clause 6 states the rule of admission:

> **Growth is governed.** A capability is admitted only as a
> receipted act: proposed, checked before it moves, decided at the
> gate, verified live by a reader who did not install it, and
> reversible under receipt. A capability that cannot be recorded
> is not in effect; a capability that cannot be expelled is never
> admitted.

## 2. The act class

`capability_install` is the ninth value of `ActionClass`. It is a
member of `HUMAN_GATES` — every install, update, deprecate, and
rollback is presented to a human approver, every time. A standing
commission never substitutes for a per-act decision: the programme
that commissions the work and the gate that approves each act are
deliberately different instruments. The class is not irreversible
— reversibility under receipt is its admission condition.

## 3. The lifecycle

- **Step 0 — Commission.** An issuer receipt, naming the Chairman's
  ratification it executes under, minted before any act. The run's
  scope is a frozen artifact, hashed; every later citation points
  at both.
- **Step 1 — Proposal.** A bundle and its content pin are
  presented. A proposal is a claim; it writes nothing.
- **Step 2 — Pre-flight.** Checks run in the install machinery's
  own order — manifest and pin recompute, substrate compatibility
  before any payload moves, license and architecture, path
  discipline, field check, scope membership with a novelty diff —
  and a refusal is a terminal, receipted outcome (Step 2's register
  is §4 below), decided by policy and never re-presentable as the
  same act.
- **Step 3 — The gate.** The governor presents an
  `EscalationRequest` whose detail is a canonical citation block:
  the verb, the bundle id, the manifest pin, the commission
  receipt, the scope artifact's hash, the governing principle's id
  and hash, the pre-flight record's hash, the novelty summary. The
  approval binds exactly that bundle, that pin, that verb.
- **Step 4 — Execution.** The manager executes under the decision's
  citation — lock, pre-flight re-check, snapshot, move, post-move
  pin check, registry bind, receipt mint. No receipt, no act: the
  move compensates and the failure is itself receipted.
- **Step 5 — Beat 1 (installed-unverified).** The installer's own
  read-back: registry state, catalog application, pin recomputed
  at the bound location. Discoverable is not live; no Chancellor
  receipt is minted for this beat.
- **Step 6 — Beat 2 (verified live).** A reader who installed
  nothing verifies the capability live. On PASS the governor opens
  probation with a chain entry citing the Step-3 decision, the
  install receipt, the Beat-2 report's hash, and the commission.
  On FAIL the capability never goes live: the arc routes to
  rollback, with the failure receipted in the rollback decision's
  rationale.
- **Steps 7–8 — Life and removal.** Use is watched through
  probation (§5). Deprecation and rollback travel the same gate
  path as install, verb named; rollback executes only onto a
  snapshot whose integrity verifies first — a rotten snapshot
  refuses the rollback and escalates rather than improvising.

**Precedence is mechanical.** A decision governs an act only when
the decision's chain position strictly pre-dates the act's
pre-flight record. A citation that arrives late is no decision.

## 4. The refusal register

Nine install refusal states join the gate's named register. Each
is a refusal Decision on the decision chain — approved = false,
decider "policy" — whose rationale carries the install machinery's
own state name verbatim plus its record hash:

| Chancellor state | Fires when |
|---|---|
| `install-incompatible` | the substrate cannot host the bundle (engine or host) |
| `install-unlicensed` | the bundle's license is unverified |
| `install-pin-mismatch` | the payload does not hash to its presented pin |
| `install-payload-escape` | a payload path escapes its staging discipline |
| `install-unconsented-build` | an executable build step lacks consent |
| `install-snapshot-failed` | the pre-move snapshot cannot be taken or verified |
| `install-out-of-scope` | the bundle or verb is outside the frozen scope |
| `install-cost-refused` | a declared cost surface is refused by the funding rule |
| `install-budget-exhausted` | the commission's attempt budget is spent (§6) |

## 5. Probation

Admission is probationary. The window is **10 receipted uses** —
a window of use, not of time; it has no expiry. A use is receipted
either by its own gate Decision (gated-class acts performed
through the capability) or by a `capability_use` entry (the
auto-approved classes). A **strike** is a graded-FAIL use, a
gate-refused use, or an out-of-permission use; **pin drift** —
the live tree no longer hashing to the admitted pin, checked at
fold time — and any out-of-permission action are one-strike
offences. **Two strikes in the window suspend the capability in
one motion**: a suspension entry citing the strike entries, the
install machinery's disable enforcement under that citation
(discovery must return zero hits in the same act), and an
escalation Decision. Suspension is not deprecation — the binding
stands, disabled; reinstatement is a fresh per-act gate decision
and re-enters probation at a fresh window. A clean window closes
with a `capability_probation_closed` entry printing the strike
count. All probation state folds from the chain; the supervisor's
status and `chancellor installs status` print it per capability —
uses, strikes, standing, and the chain head the fold was taken at.

*Stated limitation:* use records exist where a receipted writer
stands — the authoring loop and the manager's invocation point.
A general runtime interception of every gated call is designed,
not built, and is not claimed here.

## 6. Budgets

A commission carries an attempt budget. A **failed attempt** is an
approved install that fails or compensates, a Beat-2 failure, or a
rollback for cause; pre-flight refusals and gate denials are not
attempts — they cost nothing and prove the filters work. **Three
consecutive failed attempts under one commission exhaust it**:
further presentations are refused `install-budget-exhausted` as a
governor-side policy Decision and never reach the gate. The count
folds from the decision chain, so it survives restarts.

## 7. The citation bridge

Two chains meet at the install: the install machinery's registry
and receipts, and Chancellor's decision chain. Neither validates
the other. Citations are hashes and ids, never paraphrase, and a
bridge audit checks **correspondence only** — that every governed
act cites a decision that resolves on the Chancellor chain, of the
right class, strictly pre-dating it; that every refusal record
pairs with its refusal Decision. The honesty labels are the
weakest on either side, printed wherever the bridge is described:
the registry bindings are **test-grade** until the registrar
custody act; the decision chain is **consistency-grade** under the
development signer; the install machinery's issuer receipts are
production-grade.

## 8. The hearing

The act class was proven before it was claimed, in a pre-registered
install hearing: frozen scope, two doc-only bundles, legs L1–L8
(refusals, a decline, an install, independent verification,
probation, rollback, and a suspension), claims F1–F8 registered
before the run and scored by the instruments the registration
named. The full record — run card, both chains' exports, the
verifier reports, the scored results — is filed at
`docs/evidence/foundry-install-hearing/`.

## 9. Open items

Named here so they are not mistaken for built: installed-content
semantic safety (a pin proves integrity, not goodness); the
connector and schedule bundle kinds under this frame; executable
payloads and execution consent; live cost-bearing bundles under
the funding rule; the Prometheus layer; production signer and
registrar custody; concurrent-install contention beyond the
manager's single-writer lock. Each is a separate, separately
gated build.
