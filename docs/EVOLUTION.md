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

The first full-scale trial ran 5,600 Suite B runs on one machine. In Part A, governed drift was **0 of 1,800**; ungoverned drift, same workloads, was **300 of 1,800**. The zero was published with its statistical bounds printed beside it, because a zero without a denominator is a slogan: the 95% upper bound on the governed rate is **0.166%** at the run denominator (n = 1,800), and at the strictest reading — ten manifests — **25.9%**. Part B, the value-cell extension, was governed-only by design; its record says so in its own words, and this story repeats it: that zero leans on the paired governed/ungoverned control, and is reported that way.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-5 entry).

## 4 · KEEP — the supervisor, gate-passed — November 1, 2026

The Tier A supervisor — the watch that keeps the work — was completed and passed its ship gate on November 1: continuous supervision of a working agent, kill and corruption detection, chain verification before any resume, escalation when a fixed budget of recovery attempts is spent, and a signed receipt for every act, including its own refusals. Fault injection passed **15 of 15** consecutive pairs before the gate was called. Chancellor does not ship without this piece; it is the load-bearing wall.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (KEEP entries).

## 5 · The film — "a hearing in three exhibits" — November 1–2, 2026

The demonstration film was built as a hearing: three exhibits, one charge — the three questions of the ideation, put to the evidence. Narration recorded, exhibits assembled from the real runs. An earlier cut (v3) was judged and rejected — pauses between cuts too long, the background too stagnant — and stands in the record as the rejected cut. The first accepted cut (v4) carried one audio defect, a fifth-of-a-second overlap at the one-minute mark; it was diagnosed to a single narration stem, repaired by a sub-half-second shift, and re-issued as v4.1 — exactly 180 seconds, captioned — which is the film in the submission. One word in it remains open, reserved to the Chairman's ear: at about 1:47 two engines hear “receded” where the script reads “receipted”; the caption transcribes as heard, and captions can be corrected after upload without touching the film. The earlier cuts remain public as unlisted fallbacks; nothing was deleted to make the record look cleaner.

Evidence: the film itself (linked from the README and the submission).

## 6 · The 10x run (RUN-7) — November 2, 2026

The scale trial: 18,000 paired runs. Governed drift **0 of 18,000**; ungoverned drift **3,000 of 18,000**; the pooled 95% upper bound on the governed rate tightened to **0.0166%**. Alongside it, forty endurance soaks ran 19,200 segments and produced **18,403** audit-chain entries in total, with zero breaks — a pooled total across forty chains; the long soak is a separate exhibit, and its chain is not this number. The value-cell extension ran governed-only by design: drift **0 in all 200 cell instances** — 95% upper bound **2.95%** per cell instance — its zero leaning on Part A's paired control and reported that way. Every bound at every denominator was printed — 2.95% at the smallest, **1.10%** at 270 distinct manifests, 0.0166% at the pooled — and the result was later re-derived independently, hash by hash, by reviewers who did not run it (movement 11).

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-7 entry).

## 7 · The simulation bridge (RUN-8, Tier 1) — November 2, 2026

A second measurement world was built to test whether governance survives translation into simulation: paired real and simulated runs projected onto one canonical record. Tier 1 completed with the projection identical across all pairs and drift of exactly zero. Every figure from this world is labeled **simulated / virtual clock, uncalibrated** — in its records, in the README, and here. The label is part of the result.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-8 entry).

## 8 · v1.1.0 — November 1–2, 2026

The second release consolidated the supervisor and the evidence spine into the installable package: `pip install chancellor` serving the governed harness with KEEP built in, the README re-rendered on measured figures only.

Evidence: release v1.1.0 on GitHub; [BUILD-LOG.md](../BUILD-LOG.md).

## 9 · The Foundry — governed growth, and v1.2.0 — November 2, 2026

The largest increment: Chancellor learned to grow. A ninth class of consequential act — **capability install** — was added to the gate: an agent may acquire new capabilities only through the same governed arc as every other act (proposal, citation, approval, receipt, probation), under the clause the frame carries: *growth is governed*. The mechanism was proven at a pre-registered install hearing — eight legs, all passed **as registered** — before it was released in **v1.2.0** (273 tests, clean install verified cold from PyPI). The hearing's perimeter and grades are part of the result: it ran against a sandboxed copy of the manager state — the live registry was never written — with registry bindings **test-grade**, the decision chain **consistency-grade** under the development signer, and the issuer receipts **production-grade**. One claim passed only at its pre-registered boundary: for the issuer receipts at sequences 22–26, `merkle_inclusion` and `checkpoint_covers_log` fail against the issuer's existing checkpoint; coverage completes at the issuer's next checkpoint.

One claim in that hearing was later disputed and settled the hard way: see movement 11.

Evidence: [docs/evidence/foundry-install-hearing/VERIFIED-RESULTS.md](evidence/foundry-install-hearing/VERIFIED-RESULTS.md); release v1.2.0 on GitHub.

## 10 · The trial that failed honestly (RUN-9) — November 2, 2026

The supervisor's own evidence run was pre-registered claim by claim — and the apparatus around it failed in more than one way. The run's driver, the programme's own test harness, skipped 30 of its 52 scheduled fault events through a timing defect. A separate cap event left one watch collected in flight at 168/240 and the budget cell unstarted. Other instrument failures were distinct again: a pass flag that read a clean completion as a failure, and a corruption event that was never injected at all. The recount, done independently from the raw logs, printed what was actually measured: **K1 failed as pre-registered, 22/40** — of the 22 kills that were actually fired, the supervisor detected and receipted every one; **K6 failed at 215/240** segments; four claims were **not measured** at all, and the discrimination claim among them was withdrawn from the submission packet, not softened. A fifth claim-state stands beside those: K4's corruption leg was **vacuous** — never presented with a corrupted chain — so the refusal claim reverted to its build-scale wording rather than the scale wording. The recount's two lanes did not fully agree: the first passed K5 on drift 0 across 1,825 state files, while the product's own verifier passed only 14 of 18 log pairs cold — three of the four failures tails past their newest signed checkpoints, the fourth the two interleaved chains of the collection lane's disclosed double-start — and no alleged chain break in any of them; the disagreement is filed, not averaged. The run also exposed a defect in the product's own arithmetic: a 180-second stale threshold against a checkpoint cadence of about 505 seconds produced 381 stall-anomaly receipts among 596 heartbeats; K12 passed because no stale interval was ever reported healthy, and the fix — a signed cadence advisory — was built into the product from this finding. In every event that actually reached it, the supervisor behaved exactly as specified. The packet's continuity claims now carry the exception sentence the recount licensed, verbatim.

The lesson was structural, and it was not hidden: the evidence-producing harness was itself ungoverned. Its repair is movement 13. The run's public board taught the same lesson a second time: it had no path to its COMPLETE state after collection, and kept reading IN FLIGHT for a finished run until a terminal repair gave it one.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-9 entry).

## 11 · The independent review — November 2, 2026

Before submission, the whole public record was handed to independent reviewers with instructions to refute it. The scoreboard does not reduce to two numbers: **27 were confirmed** and three were refuted — and all three were repaired in the open — while one claim (F7) came back **split**, its portable legs confirmed and its issuer signature legs not portable to the reviewers' instruments, and two RUN-9 adjudications (J2, J3) were **not portable** at all. The verdict classes are printed here because a review whose unreachable claims vanish has not been reported whole:

- A precedence claim inside the Foundry hearing's scoring stands in the review's record as **refuted as filed**: over the filed exports, two install acts read late by 0.141s and 0.102s. An **errata** then re-derived the claim from the rawest sources — hash embeddings and chain sequence — and precedence held; the lateness was a truncation artifact (fractional chain timestamps read against whole-second journal stamps, and against the wrong of two pre-flight records). The errata answers the verdict; it does not erase it. The same errata disclosed that the hearing's own scoring harness had silently skipped its decision-citation leg, so the filed pass had been true but unproven by its own run.
- The README and badges were stale at the v1.2.0 tag; they were swept to the measured record (273 tests, v1.2.0), with the version attribution printed where the headline evidence was measured on the earlier tree.
- The submission packet had carried the first trial's zero without its 25.9% bound and its design caveat; both now travel with the figure everywhere it appears — including in movement 3 of this story.

The reviewers' deepest finding was not about any number: the programme's judgment — its grading — was itself uncalibrated. That became the next movement.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (independent review entry); the hearing errata inside [docs/evidence/foundry-install-hearing/](evidence/foundry-install-hearing/).

## 12 · The calibration honest negative — November 2, 2026

Chancellor grades work, so its grades must themselves be graded. The calibration remedy attempted before submission failed its completeness gate, and the project ships in the posture that failure dictates, labeled on every surface it touches: **labeled-uncalibrated**. No score from the uncalibrated suite appears anywhere in the submission. An interim rule was adopted the same day and is in force now: *an uncalibrated grade alone triggers no strike, no suspension, and no irreversible consequence* — consequential use of a grade requires a second independent basis until calibration is proven. The calibration build is the first item of the post-submission programme, sequenced ahead of every other enhancement.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md); [docs/open-register.md](open-register.md).

## 13 · The corrective (RUN-10) — launched November 2, 2026, in flight

The RUN-9 driver's defect was diagnosed to a single cause — every scheduled wait was anchored to the run's start, so events late in a long watch fell outside their window and were skipped. The driver was repaired (each wait now anchors to the previous event's completion), the repair was dry-traced against the old behaviour on identical clocks — 0 skips against 12 of 18 — and the corrected run was pre-registered with its verdict sentences written **in advance, for passing and for failing**, then launched. The launch's first act repeated the evening's lesson: b0 was first staged from a script still pointing at RUN-9's folder, which uploaded the *unrepaired* driver — the attempt failed on a missing file before any driver started or any segment ran, the script was rewritten, and the staging was hash-verified before the real start. The run's public board then crashed for five cycles when its local seed file was truncated to zero bytes in a platform failure; it recovered from the branch copy, and a marker guard was added so the splice can never again run on faith. At the time of this writing it is in flight; its recount is performed by hands that did not run it, from the raw logs, and this story claims nothing about its result. RUN-9's record stands beside it, unrewritten.

Evidence: [BUILD-LOG.md](../BUILD-LOG.md) (RUN-10 entry).

## 14 · The Engine — the product, pulled apart — November 2, 2026

The second-largest build of the day was the submission's own front door: a machine-grade interactive pull-apart of Chancellor itself, built into the landing page to the standard the Chairman had held all along — *the way Apple does it*. Real scale, closed-solid parts, solver-computed numbers, authored explode vectors, a true cutaway, a deterministic film. The plan went through the full gauntlet before a line was built — specification, adversarial pass, certification, ratification — and the census is exact: **1,435 parts**, of which 114 are authored and the rest are not illustration at all: **1,175 real audit-chain entries and 146 seals**, embedded from the judging soak's own record, arranged around the receipt chain as the machine's central shaft. Four subassemblies — Worker, Grader, Human Gate, Receipt Chain — and one hero figure, computed by the product's own solver rather than drawn: governed drift **0**, against a denominator that climbs live to 18,000. One control, fault pressure. A **TAMPER** button that alters a single character in a single real entry and lets the visitor watch the damage be *computed* — the chain re-verified, the first failure found at sequence **587**, **74** seals invalidated, **588** entries downstream, the supervisor refusing to resume with the approver seat empty and its budget untouched. A living layer was certified on top: freight that accumulates as acts, a governed bin bound to the live drift counter, a true idle when the stream is quiet.

It was verified the way the product verifies: independently, rendered, by a lane that built nothing on the page — twice, once against the pre-story build and once against the build carrying this story. The final pass found the machine underneath byte-identical in every invariant: the embedded snapshot's fingerprint unchanged, the chain re-walked clean, the census differing by **zero**, the design point exact at full precision, the TAMPER answer reproduced in four rendered presses, the sampling agreement 1,200 of 1,200, the film scanned clean, and this story's section checked figure for figure against its source. Six legs were **not executed** in either pass, each for a named instrument reason and none silently substituted: the film's pixel beats (the build exposes no stepped clock), the failure-fixture legs (no fixture builds exist), the ID-pass pixel leg (the build has no ID-pass mode), the numeric explode audit (the instrument exists nowhere on disk), the motion digests (the scene graph is not published), and frame rate as a graphics verdict (the verifying machine has no graphics hardware). The verification corrected itself once in the open, amending a stated reason when a fuller search found the fact had moved.

And it found a failure, demonstrated rather than inferred, which stands here at full size: **on phone-sized screens, the living demonstration can never start.** Its only trigger watches for a quarter of the engine section to be visible at once; the section is 7,932 pixels tall, and a phone viewport 844 pixels high can never show more than a ratio of **0.106** of it — the threshold is geometrically unattainable, by a factor of about 2.4, in any scroll posture. The verifier held the page at maximum visibility for over a thousand seconds across two sessions while every counter stood at zero, against a desktop control where the same mechanism starts exactly once and accumulates. Everything else on the phone works — the scene builds, the chain verifies, TAMPER answers exactly. The final verdict on the build was therefore **NOT CLEAN**, on that one named blocker. The repair is small and its owner is named — retarget the trigger to a part of the section a phone can actually frame — and the landing does not launch until the fix lands and the mobile leg alone has been re-run and passed. A page that argues *verify, don't trust* does not get to waive its own verdict.

Evidence: the pull-apart council's specification and the two verification reports (VERIFICATION-REPORT.md; VERIFICATION-REPORT-FINAL.md) in the programme's war room; staging deployment verified by served-byte hash.

## 15 · The submission — November 2–4, 2026

The package that goes to the Meta Global AI Developer Hackathon (Indie track, "Build for Your World") is frozen: the portal text written from the measured record and nothing else, the v4.1 film, the repository at v1.2.0, this story. The submission is made in a single sitting — the form keeps no draft — with the fields read back by a separate pass before the click, and it is reported as submitted only when the portal's own confirmation has been read back. Deadline: **Wednesday, November 4, 2026, 9:00 PM ET**. Judging runs November 4–8; the live finals are November 9.

**[The final entry of this story — the submission itself — is appended here from the portal record when it happens.]**

## Corrections — November 2, 2026

This story was audited the same evening it was published, by a council that compiled the record independently of the story and of each other. The audit found the measurements faithfully taken and the biography's own workmanship at fault in specific places. Corrected above, and recorded here rather than silently absorbed: movement 3 carried another run's fleet, another run's manifest denominator, and a caveat placed on the wrong stage; movement 6 assigned a pooled forty-chain total to a single soak; movement 9 dropped the install hearing's perimeter and grade labels; movement 10's census of its run was incomplete — a vacuous leg, a recount disagreement, a second cause — and one of its cross-references pointed at the wrong movement; movement 11's account of the independent review omitted two of its verdict classes. The portal packet carried the correct forms throughout; no measured result changed. One absence was named when this note was first filed: the Engine movement. That act is now complete — movement 14 above was written from the Engine's final verification report, its NOT CLEAN verdict carried at the same size as its passes, and the submission movement stands renumbered 15.

**Checker addendum — November 2, 2026.** The corrected text and the Engine movement were then checked independently, by hands that wrote neither, against the primary records: 80 claims examined, 77 supported as printed, cross-references 7 of 7 after the renumbering. Three minor defects were found, all of the workmanship class this note exists for, and all three are corrected above: movement 9 called a claim's pre-registered boundary a leg's; movement 10 counted the double-start's interleaved chains among the checkpoint tails (three of the four recount failures are tails; the fourth is that separate, disclosed shape); movement 6's value-cell zero travelled with its caveat but without its own bound, which now stands beside it. No measured result changed.

---

*Work is graded. Authority is gated. Every decision leaves a receipt.*
