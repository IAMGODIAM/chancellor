# The Evolution of Chancellor

*How this project was built — from the first sketch of the idea, through every release, measurement, failure, and repair, to the eve of its submission. Assembled from the project's own dated records. Every figure below carries the bound or label it was originally published with; where a measurement failed, the failure is printed at the same size as the successes. That is not a stylistic choice. It is the product's thesis, applied to its own story.*

---

## 1 · Ideation — October 29, 2026

Chancellor began as a question, not a product. AI agents can now work for hours at a stretch. Three things about that work were missing, and the project was chartered to build all three:

*When an AI agent works for hours — who grades the work? Who can say stop? And where is the proof?*

The founding decision, recorded the same day, was order of construction: build the **supervisor first** — the part that watches, grades, and can halt — before expanding the harness around it. The programme ran under the name "Warden" in its first days; the product took the name Chancellor as its shape settled: an officer who keeps the record, seals the acts, and answers for the archive.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (opening entries).

## 2 · v1.0.0 — the harness public — October 30–31, 2026

The first public release put the core bargain on the table: work is graded, consequential acts wait at a human gate, and every decision leaves a hash-chained receipt that anyone can verify offline, with no server and no trust in the operator. Graded suites, an escalation governor with a finite budget, and the receipt chain shipped together — the three answers to the three questions, in working form.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md); release v1.0.0 on GitHub.

## 3 · The first measurement (RUN-5) — October 31, 2026

The first full-scale trial ran 1,800 paired runs across ten machines. Governed drift: **0 of 1,800**. Ungoverned drift, same workloads: **300 of 1,800**. The zero was published with its statistical bounds printed beside it, because a zero without a denominator is a slogan: at the manifest denominator the 95% upper bound on the governed rate is **1.10%** (270 manifests), and at the strictest reading — ten manifests — **25.9%**. The soak half of the trial was governed-only by design; its record says so in its own words, and this story repeats it: that zero leans on the paired governed/ungoverned control, and is reported that way.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-5 entry).

## 4 · KEEP — the supervisor, gate-passed — November 1, 2026

The Tier A supervisor — the watch that keeps the work — was completed and passed its ship gate on November 1: continuous supervision of a working agent, kill and corruption detection, chain verification before any resume, escalation when a fixed budget of recovery attempts is spent, and a signed receipt for every act, including its own refusals. Fault injection passed **15 of 15** consecutive pairs before the gate was called. Chancellor does not ship without this piece; it is the load-bearing wall.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (KEEP entries).

## 5 · The film — "a hearing in three exhibits" — November 1–2, 2026

The demonstration film was built as a hearing: three exhibits, one charge — the three questions of the ideation, put to the evidence. Narration recorded, exhibits assembled from the real runs. The first accepted cut (v4) carried one audio defect, a fifth-of-a-second overlap at the one-minute mark; it was diagnosed to a single narration stem, repaired by a sub-half-second shift, and re-issued as v4.1 — exactly 180 seconds, captioned — which is the film in the submission. The earlier cuts remain public as unlisted fallbacks; nothing was deleted to make the record look cleaner.

Evidence: the film itself (linked from the README and the submission).

## 6 · The 10x run (RUN-7) — November 2, 2026

The scale trial: 18,000 paired runs. Governed drift **0 of 18,000**; ungoverned drift **3,000 of 18,000**; the pooled 95% upper bound on the governed rate tightened to **0.0166%**. Alongside it, the long soak's chain grew past eighteen thousand entries with zero breaks. Every bound at every denominator was printed — 2.95% at the smallest, 0.0166% at the pooled — and the result was later re-derived independently, hash by hash, by reviewers who did not run it (movement 11).

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-7 entry).

## 7 · The simulation bridge (RUN-8, Tier 1) — November 2, 2026

A second measurement world was built to test whether governance survives translation into simulation: paired real and simulated runs projected onto one canonical record. Tier 1 completed with the projection identical across all pairs and drift of exactly zero. Every figure from this world is labeled **simulated / virtual clock, uncalibrated** — in its records, in the README, and here. The label is part of the result.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-8 entry).

## 8 · v1.1.0 — November 1–2, 2026

The second release consolidated the supervisor and the evidence spine into the installable package: `pip install chancellor` serving the governed harness with KEEP built in, the README re-rendered on measured figures only.

Evidence: release v1.1.0 on GitHub; [BUILD-LOG.md](../BUILD-LOG.md).

## 9 · The Foundry — governed growth, and v1.2.0 — November 2, 2026

The largest increment: Chancellor learned to grow. A ninth class of consequential act — **capability install** — was added to the gate: an agent may acquire new capabilities only through the same governed arc as every other act (proposal, citation, approval, receipt, probation), under the clause the frame carries: *growth is governed*. The mechanism was proven at a pre-registered install hearing — eight legs, all passed — before it was released in **v1.2.0** (273 tests, clean install verified cold from PyPI).

One claim in that hearing was later disputed and settled the hard way: see movement 11.

Evidence: [docs/evidence/foundry-install-hearing/VERIFIED-RESULTS.md](evidence/foundry-install-hearing/VERIFIED-RESULTS.md); release v1.2.0 on GitHub.

## 10 · The trial that failed honestly (RUN-9) — November 2, 2026

The supervisor's own evidence run was pre-registered claim by claim — and the run's driver, the programme's own test harness, skipped 30 of its 52 scheduled fault events through a timing defect. The recount, done independently from the raw logs, printed what was actually measured: **K1 failed as pre-registered, 22/40** — of the 22 kills that were actually fired, the supervisor detected and receipted every one; **K6 failed at 215/240** segments; four claims were **not measured** at all, and the discrimination claim among them was withdrawn from the submission packet, not softened. In every event that actually reached it, the supervisor behaved exactly as specified. The packet's continuity claims now carry the exception sentence the recount licensed, verbatim.

The lesson was structural, and it was not hidden: the evidence-producing harness was itself ungoverned. Its repair is movement 12.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-9 entry).

## 11 · The independent review — November 2, 2026

Before submission, the whole public record was handed to independent reviewers with instructions to refute it. Of 31 claims checked against the raw evidence, **27 were confirmed**. Three were refuted — and all three were repaired in the open:

- A precedence claim inside the Foundry hearing's scoring was re-derived from the raw record; the claim held, the hearing's own scoring harness had silently skipped one leg, and an **errata** was filed into the evidence where the claim lives.
- The README and badges were stale at the v1.2.0 tag; they were swept to the measured record (273 tests, v1.2.0), with the version attribution printed where the headline evidence was measured on the earlier tree.
- The submission packet had carried the first trial's zero without its 25.9% bound and its design caveat; both now travel with the figure everywhere it appears — including in movement 3 of this story.

The reviewers' deepest finding was not about any number: the programme's judgment — its grading — was itself uncalibrated. That became the next movement.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (independent review entry); the hearing errata inside [docs/evidence/foundry-install-hearing/](evidence/foundry-install-hearing/).

## 12 · The calibration honest negative — November 2, 2026

Chancellor grades work, so its grades must themselves be graded. The calibration remedy attempted before submission failed its completeness gate, and the project ships in the posture that failure dictates, labeled on every surface it touches: **labeled-uncalibrated**. No score from the uncalibrated suite appears anywhere in the submission. An interim rule was adopted the same day and is in force now: *an uncalibrated grade alone triggers no strike, no suspension, and no irreversible consequence* — consequential use of a grade requires a second independent basis until calibration is proven. The calibration build is the first item of the post-submission programme, sequenced ahead of every other enhancement.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md); [docs/open-register.md](open-register.md).

## 13 · The corrective (RUN-10) — launched November 2, 2026, in flight

The RUN-9 driver's defect was diagnosed to a single cause — every scheduled wait was anchored to the run's start, so events late in a long watch fell outside their window and were skipped. The driver was repaired (each wait now anchors to the previous event's completion), the repair was dry-traced against the old behaviour on identical clocks — 0 skips against 12 of 18 — and the corrected run was pre-registered with its verdict sentences written **in advance, for passing and for failing**, then launched. At the time of this writing it is in flight; its recount is performed by hands that did not run it, from the raw logs, and this story claims nothing about its result. RUN-9's record stands beside it, unrewritten.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-10 entry).

## 14 · The submission — November 2–4, 2026

The package that goes to the Meta Global AI Developer Hackathon (Indie track, "Build for Your World") is frozen: the portal text written from the measured record and nothing else, the v4.1 film, the repository at v1.2.0, this story. The submission is made in a single sitting — the form keeps no draft — with the fields read back by a separate pass before the click, and it is reported as submitted only when the portal's own confirmation has been read back. Deadline: **Wednesday, November 4, 2026, 9:00 PM ET**. Judging runs November 4–8; the live finals are November 9.

**[The final entry of this story — the submission itself — is appended here from the portal record when it happens.]**

---

*Work is graded. Authority is gated. Every decision leaves a receipt.*
