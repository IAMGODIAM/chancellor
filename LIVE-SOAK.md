# Chancellor — the judging-week soak, live

This branch carries the public record of a soak test of the **frozen
submission tree** of [Chancellor](https://github.com/IAMGODIAM/chancellor)
(the Meta Global AI Developer Hackathon entry, Indie track), launched
2026-11-01 ahead of judging and running through finals on 2026-11-09.

The soak is the RUN-5 endurance instrument run at judging-week length:
**11,520 segments** of governed work (12 steps each, 138,240 steps in
all), one segment a minute by design — 12 steps at 5 s of step latency
— across the eight days of judging week and finals, with a fault
injected every
ten segments — 1,152 faults in all, drawn from the same classes the
Suite B frontier measures (value, omit, timing, crash, valueopt). Every
segment's gate decision lands in a hash-chained audit log with signed
checkpoints; the log's snapshot is published beside this file and
refreshed hourly by an automated backstop.

## Status

<!-- STATUS:BEGIN -->
- **Segments done:** 9 / 11,520
- **Steps executed:** 108
- **Faults injected so far:** 0 (the first lands at segment 10; one
  every ten segments thereafter)
- **Segments complete / halted (fail-closed):** 9 / 0
- **Drift events:** 0
- **Audit chain:** 10 entries · 1 signed checkpoint at last verify
- **Last chain verification:** VERIFIED — the soak's own verify at
  step 108 (ok, no failures) and an independent run of the product's
  verifier against the snapshot published with this status
- **Process kills resumed from checkpoint so far:** 1 (a deliberate
  proof kill at segment 3, before this page first published — the
  service restarted the soak, the chain verified across the kill)
- **Status as of:** 2026-11-01 12:16 EST (refreshed hourly from the
  soak's own state)
<!-- STATUS:END -->

## How to read a halt — the language of this page, filed before the first segment

**A halted segment is the product working.** When an injected fault
corrupts a step's output, the governed run refuses to claim that work:
the segment halts fail-closed rather than completing on corrupted
state, the halt is counted and published here, and the run continues
with the next segment. A rising halted count under a rising fault count
is the design behaving as designed.

**Drift is the failure this page exists to make visible** — a run
claiming success for work whose final state failed its check. The drift
counter on this page is expected to read **zero** for the entire run.
If it ever reads nonzero, that is the headline, not a footnote, and it
will not be edited away: the counters above are refreshed mechanically
from the soak's own state files, and the audit-log snapshot published
beside this file lets any reader check every count independently.

The soak process itself is supervised so that a kill — a crashed
process, a replaced machine — becomes a resume from the last
checkpoint, not an ending. That, too, is the product's claim, being
made in public: crash-atomic state, resumed work, an unbroken chain.

## Verify the chain yourself

Download `audit-snapshot.jsonl` and
`audit-snapshot.jsonl.checkpoints.jsonl` from this branch (they must
sit side by side), install the package from the repository, and run the
verifier the product ships — offline, no credentials, no network:

```bash
python -m chancellor.verify_log audit-snapshot.jsonl
```

Exit 0 means the chain is intact and the newest signed checkpoint
checks out. Exit 1 names the failure — a mid-log edit, a reordering, a
truncated tail, a forged checkpoint. Each snapshot is cut at the
newest signed checkpoint, so the pair you download verifies exactly:
the live log runs a few entries ahead of the snapshot at any moment,
and the next hourly refresh closes the gap. The chain the snapshot
verifies is the chain the soak is still writing.

*Filed 2026-11-01. The halt language above was written before the
first segment ran, and stands for the whole run.*
