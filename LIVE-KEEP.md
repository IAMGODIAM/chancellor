# CHANCELLOR — THE KEEP, LIVE

*The live board of RUN-10 · the KEEP corrective evidence run · E5 Enclave Inc.*

---

Chancellor's story has always had three elements. The work is graded.
Authority is gated. Every decision leaves a receipt. With 1.1.0 a
fourth element took its seat — **the watch that keeps them**: the
supervisor, the KEEP office, which stands over a long-running agent
and does not look away. It notices a death and proves the cause
before it speaks. It verifies the chain before it resumes anything.
It refuses what fails verification, and it receipts its refusals.
This board is that watch, watched — the supervisor's own evidence
run, displayed in the live way, while it runs.

## Why a corrective run

RUN-9 put the supervisor on trial and the supervisor passed every
test that reached it — but the test driver, a script that fires
scheduled failures at the agent, kept missing its own appointments:
its fixed 30-minute wait windows were shorter than the gaps between
late events, and 30 of its 52 scheduled events never fired. Four
measurements never happened. RUN-10 is the same trial re-run with
the driver's scheduling repaired — each wait now opens at the
previous event's completion and carries no fixed window — measuring
exactly what RUN-9's harness ate, under a new card, on the current
release tree. RUN-9's record stands as filed beside it, unrewritten.

## The Live Lab

The board tallies; the lab listens. Beside this board stands a
composed page that renders the supervisor's own receipts as what
they are — the conversation the system has with itself: noticing,
diagnosing, checking the chain, and only then correcting, each
line in the supervisor's own signed words, refreshed on this
board's cadence. [The Live Lab — RUN-10 in
dialogue](https://iamgodiam.github.io/chancellor/keep-lab.html).

## The four elements

**I · The Work Is Graded.** No agent marks its own homework. On this
board: segments of governed work, completed or halted fail-closed
under injected faults, counted from the agents' own checkpoints.

**II · Authority Is Gated.** Consequential acts wait at a gate; what
the gate refuses is receipted, not waved through. Refusals on this
run are events of record, printed below when they occur.

**III · Every Decision Leaves a Receipt.** Hash-chained audit logs
with signed checkpoints, on the agent's side and the supervisor's
side alike — two chains per watch, each verifiable cold, offline,
by anyone holding the pair.

**IV · The Watch That Keeps Them.** The KEEP supervisor itself, on
trial at soak scale in RUN-10: forty scheduled kills across two
machines, the supervisor's own death and restart, corruption offered
to it live and under a kill, stalls dressed as deaths and deaths
dressed as stalls, an escalation budget spent to its last unit, and
— as one box's final act — the loss of the machine itself, whose
pre-registered expectation is that no recovery is claimed. What the
watch does is receipted in its own log; this board tallies those
receipts as they land.

## Status

<!-- STATUS:BEGIN -->
- **Standing:** IN FLIGHT — every figure UNVERIFIED, republished from the boxes’ own state files.
- **As of:** 2026-11-03 00:32 EST (five-minute cadence)
- **Boxes reporting:** 4 / 4
- **Segments:** 1514 / 1440 across the watches polled · complete 1396 · halted fail-closed 118 · faults injected 150
- **Drift events:** 0
- **The watch's receipts so far:** refusals 4 · escalations 4 · agent_completed 5 · budget_exhausted 1 · cadence_advisory 14 · chain_verification 41 · drift_detected 1 · escalation 4 · interruption_detected 47 · resume_confirmed 29 · resume_failed 9 · resume_launched 39 · stall_anomaly 209 · supervision_started 14

### Box b0 — Cell A — kill cycle · us-east-1
- **Phase:** DONE · **Step:** all · *all supervised runs finished*
- **Watch 10101:** segments 240 / 240 · complete 221 · halted 19 · faults 24 · drift 0 · corrupted state files 0 · in-run chain verifications 28/28 ok · supervision receipts 155 (refusals 0, escalations 0) · latest watch event: *supervisor: agent completed*
- **Watch 10102:** segments 240 / 240 · complete 222 · halted 18 · faults 24 · drift 0 · corrupted state files 0 · in-run chain verifications 28/28 ok · supervision receipts 160 (refusals 0, escalations 0) · latest watch event: *supervisor: agent completed*

### Box b1 — Cell A — kill cycle (replication) · us-west-1
- **Phase:** DONE · **Step:** all · *all supervised runs finished*
- **Watch 10103:** segments 240 / 240 · complete 224 · halted 16 · faults 24 · drift 0 · corrupted state files 0 · in-run chain verifications 28/28 ok · supervision receipts 156 (refusals 0, escalations 0) · latest watch event: *supervisor: agent completed*
- **Watch 10104:** segments 232 / 240 · complete 211 · halted 21 · faults 23 · drift 0 · corrupted state files 0 · in-run chain verifications 27/27 ok · supervision receipts 148 (refusals 1, escalations 1) · latest watch event: *supervisor escalation: resume budget exhausted*

### Box b2 — Cell B — supervisor death + refusal · us-east-1
- **Phase:** DONE · **Step:** all · *all supervised runs finished*
- **Watch 10105:** segments 240 / 240 · complete 220 · halted 20 · faults 24 · drift 0 · corrupted state files 0 · in-run chain verifications 28/28 ok · supervision receipts 125 (refusals 0, escalations 0) · latest watch event: *supervisor: agent completed*
- **Watch 10108:** segments 7  · complete 7 · halted 0 · faults 0 · drift 0 · corrupted state files 0 · in-run chain verifications 0/0 ok · supervision receipts 8 (refusals 1, escalations 1) · latest watch event: *supervisor escalation: chain verification failed — resume refused*
- **Watch 10109:** segments 50  · complete 46 · halted 4 · faults 5 · drift 0 · corrupted state files 0 · in-run chain verifications 5/6 ok · supervision receipts 26 (refusals 1, escalations 1) · latest watch event: *supervisor escalation: chain drift detected under a live agent*
- **Watch 10110:** segments 25  · complete 24 · halted 1 · faults 2 · drift 0 · corrupted state files 0 · in-run chain verifications 3/3 ok · supervision receipts 16 (refusals 1, escalations 1) · latest watch event: *supervisor escalation: chain verification failed — resume refused*

### Box b3 — Cell C — stall vs death, then D — machine loss (staged) · us-west-1
- **Phase:** DONE · **Step:** all · *all supervised runs finished*
- **Watch 10106:** segments 240 / 240 · complete 221 · halted 19 · faults 24 · drift 0 · corrupted state files 0 · in-run chain verifications 28/28 ok · supervision receipts 119 (refusals 0, escalations 0) · latest watch event: *supervisor: agent completed*

<!-- STATUS:END -->

## How to read this board — the language, filed before the first kill

**A halted segment is the product working.** When an injected fault
corrupts a step's output, the governed run refuses to claim that
work: the segment halts fail-closed, the halt is counted here, and
the run continues from its last signed checkpoint.

**A refusal is the watch working.** When verification fails — a
chain that does not re-walk, a state that does not re-derive — the
supervisor resumes nothing over it. It escalates, and the refusal is
receipted in the supervision log. A refusal on this board is a
claim being proven, not an incident being hidden.

**A stall is not a death, and the watch says which.** A process
alive with a stale checkpoint is receipted as a stall anomaly and
no second copy is started. A death is receipted with its cause
graded — proven, plausible, or unknown — and never upgraded after
the fact.

**The stall receipts on this run carry a filed diagnosis.** The
instrument signs a checkpoint every ~505 s against the supervisor's
180 s stale threshold, so healthy watches earn stall receipts on a
cadence sawtooth — diagnosed background, per RUN-9's
`DIAGNOSIS-STALL-ANOMALY.md`. They are counted here as what they
are; only a true freeze — stalls growing while the signed boundary
and the raw audit entries both sit static and no resume lands in
the window, all three legs at once (the rule as refined after
RUN-9's freeze-9102 false positive) — is paged as an anomaly.

**Drift is the failure this board exists to make visible** — work
claimed for a state that failed its check. The drift counters are
expected to read **zero** for the entire run. If one ever reads
nonzero, that is the headline, not a footnote, and it will not be
edited away.

**Every figure here is IN FLIGHT and UNVERIFIED.** This board is a
window, not evidence: it republishes the boxes' own state files on
a five-minute cadence and asserts nothing as proven. The evidence
is the independent recount — an outside parser, no product code —
filed after collection as `results/VERIFIED-RESULTS.md` in the
run's war room, scoring the pre-registered claims K1–K12 against
the fault plans committed before launch. Cell D, the machine-loss
cell, is staged by design: it begins at collection, after Cell C's
pull verifies, so the fourth box standing DONE and still beaconing
is the design holding, not a box lost.

*Filed 2026-11-02, beside the judging soak's live page, in its
pattern. The language above was written before the run's first
kill was scored, and stands for the whole run.*
