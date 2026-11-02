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

## The Live Lab

The board tallies; the lab listens. Beside this board stands a
composed page that renders the supervisor's own receipts as what
they are — the conversation the system has with itself: noticing,
diagnosing, checking the chain, and only then correcting, each
line in the supervisor's own signed words, refreshed on this
board's cadence. [The Live Lab — RUN-9 in
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
- **As of:** 2026-11-02 07:47 EST (five-minute cadence)
- **Boxes reporting:** 4 / 4
- **Segments:** 855 / 1440 across the watches polled · complete 788 · halted fail-closed 67 · faults injected 82
- **Drift events:** 0
- **The watch's receipts so far:** refusals 0 · escalations 0 · chain_verification 10 · interruption_detected 10 · resume_confirmed 7 · resume_failed 2 · resume_launched 10 · stall_anomaly 109 · supervision_started 6

### Box b0 — Cell A — kill cycle · us-east-1
- **Phase:** RUN · **Step:** seed-9102 · *supervised soak started*
- **Watch 9101:** segments 149 / 240 · complete 138 · halted 11 · faults 14 · drift 0 · corrupted state files 0 · in-run chain verifications 17/17 ok · supervision receipts 76 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*
- **Watch 9102:** segments 145 / 240 · complete 135 · halted 10 · faults 14 · drift 0 · corrupted state files 0 · in-run chain verifications 17/17 ok · supervision receipts 102 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

### Box b1 — Cell A — kill cycle (replication) · us-west-1
- **Phase:** RUN · **Step:** seed-9104 · *supervised soak started*
- **Watch 9103:** segments 141 / 240 · complete 129 · halted 12 · faults 14 · drift 0 · corrupted state files 0 · in-run chain verifications 16/16 ok · supervision receipts 64 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*
- **Watch 9104:** segments 143 / 240 · complete 130 · halted 13 · faults 14 · drift 0 · corrupted state files 0 · in-run chain verifications 17/17 ok · supervision receipts 64 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

### Box b2 — Cell B — supervisor death + refusal · us-east-1
- **Phase:** RUN · **Step:** seed-9105 · *supervised run starting (B-main)*
- **Watch 9105:** segments 139 / 240 · complete 130 · halted 9 · faults 13 · drift 0 · corrupted state files 0 · in-run chain verifications 16/16 ok · supervision receipts 63 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

### Box b3 — Cell C — stall vs death, then D — machine loss (staged) · us-west-1
- **Phase:** RUN · **Step:** seed-9106 · *supervised run starting (C)*
- **Watch 9106:** segments 138 / 240 · complete 126 · halted 12 · faults 13 · drift 0 · corrupted state files 0 · in-run chain verifications 16/16 ok · supervision receipts 62 (refusals 0, escalations 0) · latest watch event: *supervisor: agent stalled — checkpoint stale, process alive*

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

**Correction, filed where the alarm appeared.** The freeze page
raised on watch 9102 at 06:01 EST on 2026-11-02 was adjudicated a
detector false positive: the watch was healthy and actively
resuming inside one ordinary checkpoint interval that held a
back-to-back kill pair (`DIAGNOSIS-FREEZE-9102.md` in the run
folder). The freeze rule now requires all three legs at once —
the signed boundary static, the raw audit entries static, and no
resume activity in the window — and a window failing any leg is
filed here as background, with the leg named.

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
