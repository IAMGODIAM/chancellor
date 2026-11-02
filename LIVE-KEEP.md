# CHANCELLOR — THE KEEP, LIVE

*The live board of RUN-9 · the KEEP evidence run · E5 Enclave Inc.*

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
trial at soak scale in RUN-9: forty scheduled kills across two
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
- **As of:** 2026-11-02 05:56 EST (five-minute cadence)
- **Boxes reporting:** 4 / 4
- **Segments:** 170 / 1440 across the watches polled · complete 161 · halted fail-closed 9 · faults injected 14
- **Drift events:** 0
- **The watch's receipts so far:** refusals 0 · escalations 0 · chain_verification 2 · interruption_detected 2 · resume_confirmed 2 · resume_launched 2 · stall_anomaly 21 · supervision_started 6

### Box b0 — Cell A — kill cycle · us-east-1
- **Phase:** RUN · **Step:** seed-9102 · *supervised soak started*
- **Watch 9101:** segments 35 / 240 · complete 33 · halted 2 · faults 3 · drift 0 · corrupted state files 0 · in-run chain verifications 4/4 ok · supervision receipts 21 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*
- **Watch 9102:** segments 36 / 240 · complete 33 · halted 3 · faults 3 · drift 0 · corrupted state files 0 · in-run chain verifications 4/4 ok · supervision receipts 20 (refusals 0, escalations 0) · latest watch event: *supervisor: resume confirmed — chain advancing past the loss point*

### Box b1 — Cell A — kill cycle (replication) · us-west-1
- **Phase:** RUN · **Step:** seed-9104 · *supervised soak started*
- **Watch 9103:** segments 26 / 240 · complete 25 · halted 1 · faults 2 · drift 0 · corrupted state files 0 · in-run chain verifications 3/3 ok · supervision receipts 13 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*
- **Watch 9104:** segments 26 / 240 · complete 25 · halted 1 · faults 2 · drift 0 · corrupted state files 0 · in-run chain verifications 3/3 ok · supervision receipts 13 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

### Box b2 — Cell B — supervisor death + refusal · us-east-1
- **Phase:** RUN · **Step:** seed-9105 · *supervised run starting (B-main)*
- **Watch 9105:** segments 24 / 240 · complete 23 · halted 1 · faults 2 · drift 0 · corrupted state files 0 · in-run chain verifications 2/2 ok · supervision receipts 12 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

### Box b3 — Cell C — stall vs death, then D — machine loss (staged) · us-west-1
- **Phase:** RUN · **Step:** seed-9106 · *supervised run starting (C)*
- **Watch 9106:** segments 23 / 240 · complete 22 · halted 1 · faults 2 · drift 0 · corrupted state files 0 · in-run chain verifications 2/2 ok · supervision receipts 11 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

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
cadence sawtooth — diagnosed background, per
`DIAGNOSIS-STALL-ANOMALY.md` in the run folder. They are counted
here as what they are; only a true freeze — stalls growing while a
checkpoint stops advancing — is paged as an anomaly.

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
run's war room, scoring the twelve pre-registered claims K1–K12
against the fault plans committed before launch. Cell D, the
machine-loss cell, is staged by design: it begins at collection,
after Cell C's pull verifies, so the fourth box standing DONE and
still beaconing is the design holding, not a box lost.

*Filed 2026-11-02, beside the judging soak's live page, in its
pattern. The language above was written before the run's first
kill was scored, and stands for the whole run.*
