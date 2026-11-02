# Benefits-realization memo — opening the rest of the council record

**Charge.** The Chairman approved the CAPPZ council's design-stage
buttons (Suite C design, cap-object spec, signer-separation design)
and the parallel builds (count-in-anchor, frame-named receipts, the
continuity supervisor), and charged the council with the follow-on
question: *for everything else the council graded, how does the
benefit open — as an enhancement on machinery Chancellor already
has?* This memo answers for each remaining disposition.

**The no-copy rule, restated as method.** The Chairman's ruling of
2026-11-01 governs every item below: *"You can't copy it. You can
borrow inspiration — that's what REA is for."* In practice:
mechanisms arrive as graded patterns in the council record; what
Chancellor builds is written in Chancellor's own words, shapes,
and vocabulary, fitted to Chancellor's existing surfaces, with the
pattern cited where it is used (the nod). No CAPPZ code, formats,
or text is reproduced in anything this memo proposes. Where a
public standard carries the construction (RFC 9162, RFC 9421),
Chancellor builds on the standard, not on Derek's implementation
of it.

**Scope.** Covered here: M3, M7, M9, M10, M4, M11. Not covered
(theirs are separate lanes/documents): M2 count-in-anchor and M6
frame-named receipts (the receipts build lane), M1/Button 5, M5/
Button 4, M8/Button 2 (their own design documents, filed alongside
this memo), and the continuity supervisor (built; Continuity
Analysis). Nothing in this memo is a build approval — each item
states its first step and cost class; taps and builds remain the
Chairman's.

---

## M3 — Evidence custody: k-of-n sharding, hash-verified

**The benefit.** Chancellor's measured record — `docs/evidence/`,
soak audit logs, run archives — is the product's proof. Today it
survives by being copied, which is a habit, not a posture. The
pattern (commodity mathematics; no patent flag) upgrades custody
to a stated guarantee: the evidence set sharded k-of-n across owned
stores, every shard hash-checked before use, a corrupted shard
counting as *missing* rather than silently corrupting, the whole
rebuildable from any k shards.

**How it opens on existing machinery.** Chancellor already computes
SHA-256 hashes and Merkle roots over everything it keeps
(`receipts.py`). The custody layer consumes those hashes as the
shard-verification keys — no new cryptography, no new dependency
(Reed-Solomon over GF(2⁸) is mathematics, adopted as mathematics —
not as a package). The evidence
files themselves do not move and are never replaced by shards
(Wabi's condition): shards are an additional custody surface beside
the originals.

**Conditions that bind (Crowley, preserved from the record).**
(1) The **reconstruction admittance test is a hard gate**: no
custody implementation is admitted until it demonstrably passes —
lose n−k shards, rebuild, compare hashes against the originals.
The source project's own history is the warrant for this severity:
their storage layer claimed Reed-Solomon and shipped XOR parity —
every "parity" shard an identical copy, surviving exactly one
loss, undiscovered until they measured it. A custody claim without
a reconstruction test is the storage form of an unrun gate.
(2) The record may not call this "survival" until shards sit under
**genuinely separate failure domains**. k-of-n across stores one
operator and one account control is protection against disk rot
and single-store loss — real, and worth having — but the failures
that actually happen at the account level (account loss, provider
action) take all the shards together. The custody spec must name
which failure domains its placement covers and which it does not,
in the anchoring-disclosure spirit of the continuity design.

**First step.** Write the evidence-custody spec: k/n parameters
per evidence class, per-shard hash verification, corrupt-counts-
as-missing, the admittance test as the admittance test, and the
failure-domain placement table. **Cost class: $0 pattern** (spec);
implementation, when approved, $0 code on owned infra.

## M7(a) — Test-proof records

**The benefit.** "188 passed" in a README is a sentence. The
pattern makes it a record: every release's gate run becomes a
signed test-proof record bound to the tree hash, filed in
`docs/evidence/`, which the README's re-render cites — so the
claim is resolvable by anyone, offline, against the exact tree it
describes.

**How it opens on existing machinery.** The audit chain already
signs checkpoints over arbitrary governed records; the gate suite
already emits structured results (pytest/ruff/mypy outcomes the
build lanes quote). The enhancement is bookkeeping, and it is
small: at release time, emit the gate results as a record in the
existing checkpoint machinery, file it, cite it from BUILD-LOG,
and let the regeneration rule point at the record instead of at a
memory of a run. This makes the README's regeneration rule
*enforceable* (Wabi): a README citing a record can be checked; a
README citing a memory cannot.

**First step.** At the next release (no separate tap — the council
record folds this into release bookkeeping): emit + file + cite.
**Cost class: $0 pattern → $0 code on owned infra.**

## M7(b) — Skill-binding discovery, into Confluence G-CARD

**The benefit.** Confluence — Chancellor's agent-to-agent protocol
— has its first two steps greenlit and unactioned: G-CARD (signed
capability/identity cards) and G-SIGN (signed message exchange).
The open design question inside G-CARD is discovery: how does a
peer learn what another peer can do, and — harder — stop trusting
what it no longer offers? The graded pattern answers with a signed
registry walked for bound capabilities and **event-driven
invalidation**: when a binding is created, deprecated, or amended,
subscribers learn it from the event, not from polling a hosted
service.

**How it opens on existing machinery.** As *prior art for
Confluence's own design documents*, in Confluence's own vocabulary
(Crowley's caution, binding): capability cards as signed records
(Chancellor's chain already signs records); deprecation as a
first-class signed event; subscribers honoring deprecation as they
honor any receipted act. Nothing is imported — not their registry
walk, not their TTL, not their event names (§ of the record: the
moment Confluence imports the protocol shapes, it is downstream of
another project; ADAPT means the questions are answered in our own
documents, cited).

**First step.** When the G-CARD design is written (already
greenlit at $0), include the discovery/invalidation section
answering: card format, deprecation event, subscriber behavior —
with the citation "discovery/invalidation pattern after
LaSalle/CAPPZ skill bindings (AX-70)". **Cost class: $0 pattern.**

## M9 — Evidence-gated cutover

**The benefit.** Chancellor's live surfaces — the landing page
hosting, the published evidence, README re-renders — are few but
real, and a bad replacement ships instantly. The pattern:
**shadow → compare → cut over or roll back → signed record.**
Old and new run side by side; the comparison is filed; the cutover
happens only on evidence; the decision is a record.

**How it opens on existing machinery.** It mostly names what the
house already does (gated deploys, design-gate passes, read-backs)
and adds the two pieces that were missing: an explicit *compare
step with a stated criterion per surface* — byte-equal,
figure-equal, or behavior-equal, chosen before the shadow runs
(Wolfram's condition: an unstated criterion degrades "evidence" to
eyeballing) — and a *cutover record* in BUILD-LOG form: what was
shadowed, what the comparison showed, which way it went.

**First step.** One checklist note in the release discipline:
no Chancellor surface is replaced on a builder's say-so; the
replacement shadows, the comparison files, the cutover is a
record. Pattern note credited ("evidence-gated cutover formulation
after LaSalle/CAPPZ `/port`"). No build, no tooling (Crowley).
**Cost class: $0 pattern.**

## M10 — Refusal receipts: confirming the fold

**Confirmation.** The council record folded refusal receipts into
Button 3's record-format change (same surface — the receipt
format — same window). The Chairman has since approved Button 3's
lane (frame-named receipts). **This memo confirms the fold and
states its content so the lane cannot lose it:** when the receipt
format next changes, it changes to carry *both* additions —

1. the frame identifier and frame hash inside the signed payload
   (M6/Button 3 proper), and
2. **refusal as a first-class receipted outcome at every gate:**
   every refusal issues a receipt carrying a named refusal state.
   Chancellor's initial state vocabulary, enumerated from the
   existing gate and the approved specs: `no-approver-attached`
   (already the live behavior — the record shows a publish held
   and receipted as denied), `approver-declined`, `cap-mode-off`,
   `cap-window-exceeded`, `cap-ceiling-exceeded`,
   `cap-command-unavailable` (cap spec §3), `frame-mismatch`
   (a record presented under a frame version the verifier does not
   hold), and `verification-failed` (the supervisor's R3 state,
   when continuity receipts are the surface).

**Design constraints carried from the record.** A refusal receipt
must be issuable **by the gate alone, without the refused party's
cooperation** — a party that can decline to be recorded can erase
its refusals by refusing (Crowley, adopted). Refusals complete the
denominator (Wolfram): a gate whose record counts only approvals
cannot be audited for selectivity; with refusals receipted, both
sides of every decision are countable. The underlying signature
standard in the source design is a public IETF standard (RFC
9421); the KeyZ declaration layer beneath the source's gateway
remains under M1's OWNER-GATE and is not part of this fold — the
pattern adapted here is our gate, our states, our chain (Manus's
adjacency flag, restated).

**First step.** None separate — the fold rides the frame-receipts
build. If that build's scope is ever trimmed, this memo is the
record that the refusal half must be re-buttoned, not dropped.
**Cost class: $0 pattern** (rides an approved lane).

## M4 — Wallet envelopes: STUDY — what graduation requires

**Where it stands.** The grammar is genuinely good — a fresh key
per record; purpose and scope bound as context so a record cannot
be opened as another purpose's record; grants made by re-wrapping
one record's key for one declared recipient; undeclared,
wrong-purpose, expired, or revoked recipient keys refused by
default. It is also the **strongest patent-proximity flag in the
delta** (the patent's named subject is privacy-protected
credential containers with local validation and access control),
and Chancellor today has **no live surface that needs it**: the
record is deliberately public, and the one custody item (a live
capture) stands declined on a ground envelope grammar does not
cure.

**What would have to be true for it to graduate.**
1. A real sealed-record surface exists — named recipients, a
   reason the record must not be public (sealed calibration
   material is the standing candidate), and a threat model written
   down. No surface, no build: sealing a public record is cost
   without benefit.
2. The Chairman's licensing conversation has addressed the
   flagged territory — graduation from STUDY goes through his
   gate regardless of how clean the engineering looks, because
   this item is the one where "we studied the pattern" most needs
   his lane before it becomes anything else.
3. The refusal-by-default and context-binding semantics survive
   translation into Chancellor's own format design — if a future
   design cannot keep both, it has not graduated the pattern, it
   has borrowed the name.

**What we watch meanwhile.** Whether the sealed-calibration or
custody lanes ever produce a genuine named-recipient requirement;
the custody spec's study annex keeps the grammar findable (with
full citation) until then. **Cost class: STUDY — $0**; any future
build OWNER-GATE patent-flagged.

## M11 — Staged-payment hold: STUDY — what graduation requires

**Where it stands.** For Chancellor itself, there is no plug and
this memo says so plainly: Chancellor's gates hold *acts* for
approval, not *results* for payment, and attaching a payment hold
to the consent gate would price the office. (Crowley's minority
position in the record — NOT TAKEN for Chancellor itself, STUDY
for the fleet file only — is preserved; the majority's STUDY
stands because the pattern has a real home elsewhere.) The home
is the fleet's revenue lanes, where pay-per-stage agent work is a
live question and a hold-until-validated escrow shape is a clean
answer.

**What would have to be true for it to graduate.**
1. A named revenue lane adopts staged delivery as its commercial
   shape — a buyer, a stage definition, a validation event that is
   not the seller's say-so (a Chancellor verdict is the obvious
   candidate, which is this pattern's one genuine Chancellor
   adjacency: governance as the release condition on someone
   else's escrow, with Chancellor itself never holding the money).
2. The money lane's own approvals clear — any money movement is
   Chairman-gated regardless of this memo, and payment circuits
   carry their own patent-proximity flag (G06Q20 classifications;
   proximity only).
3. The token denomination stays out: the source's on-ledger
   settlement in a project token is NOT TAKEN (§3 of the record);
   a graduated design settles in ordinary rails or not at all.

**What we watch meanwhile.** The revenue lanes' first staged-work
engagement, whenever it lands; this memo's study note is filed
where that lane will find it. **Cost class: STUDY — $0.**

---

## Summary table

| Item | Benefit opens as | First step | Cost class |
|---|---|---|---|
| M3 custody | Custody spec beside the evidence, hashes as shard keys | Write the custody spec incl. admittance test + failure-domain table | $0 pattern |
| M7(a) test-proofs | Signed gate-run records the README cites | Emit + file + cite at next release | $0 pattern → $0 code |
| M7(b) discovery | Design prior art inside G-CARD | Discovery/invalidation section in the G-CARD design | $0 pattern |
| M9 cutover | Release-checklist discipline + cutover records | One checklist note, criterion stated per surface | $0 pattern |
| M10 refusals | **Fold confirmed** into the frame-receipts build | Rides Button 3's lane; re-button if trimmed | $0 pattern |
| M4 envelopes | STUDY | Annex in the custody spec; watch for a sealed-record surface | STUDY $0 |
| M11 staged payment | STUDY (fleet file) | Watch the revenue lanes; Chancellor never holds money | STUDY $0 |

*Memo ends. Every item above is an enhancement path on machinery
Chancellor already has, under the no-copy rule, with its first
step priced. The taps remain the Chairman's.*
