# Changelog

The head entry names the current release and its date; it is the entry
the release gate binds (its version must equal the pyproject
declaration, its date the CITATION `date-released`). Entries below the
head are record — their words are the releases' own and are never
rewritten by sync machinery.

*Migration note (2026-11-03): this file was created by the release-sync
migration. The entries for 1.2.1, 1.2.0, and 1.0.0 are assembled from
those releases' GitHub Release bodies; 1.1.0 had neither a git tag nor
a GitHub Release, so its entry is assembled from the README's own
"What's new in 1.1.0" section. The words are the releases' own in
every case.*

## [1.2.1] — 2026-11-03

Two supervisor correctness fixes. Both were found after 1.2.0 shipped, both are proven by regression tests that ship with them, and the full suite stands at **287 passing** with Ruff and mypy clean.

- **A first launch onto existing state is a resume — F-WABI-001, closed.** The supervisor's initial chain verification is now honored whenever a pre-existing agent log exists and is non-empty on disk: file presence and size, not parseability. Before the fix, a malformed agent log with zero parseable entries and a missing checkpoint sidecar was adopted as a fresh start, and the agent launched onto an unverified chain with nothing receipted. A zero-byte log still starts fresh, and a sidecar committing entries against an empty log still fails as truncation. The hole was reported by an outside verifier on the bridge council and independently confirmed before it was fixed.
- **The boundary verifier recounts a torn read — O1, closed.** Verification reads the agent log first and the checkpoint sidecar second; a writer that appends and checkpoints between the two reads leaves the sidecar ahead of the counted entries, and the tear read as tail truncation — halting healthy live agents on false drift verdicts. On that signature alone, the verifier now re-reads the pair fresh and judges on the consistent second read alone; a truncation that persists across the recount is real and still fails, as do genuine corruptions. Found by the second-seat acceptance programme, with three receipted sightings, each of which re-verified clean cold.

Nothing else changes: no second-seat code (that is its own later release), no new surface, no behavior change on any path either fix does not name.

**Calibration posture unchanged:** judge verdicts remain labeled *uncalibrated* under the interim calibration rule, exactly as in 1.2.0. Signatures remain tamper-evidence under the development signer, not non-repudiation, as documented.

## [1.2.0] — 2026-11-02

**Capability install is a governed act.** Frame v2 adds clause 6 — growth is governed — and a ninth gated act class, `capability_install`: an agent gaining a new capability is proposed, compatibility-checked before anything moves, decided at the human gate, receipted across two chains joined by a citation bridge, verified live by a reader who did not install it, watched through a probationary window (first 10 receipted uses; suspension in one motion at strike 2; pin drift suspends at strike 1), and reversible under a compensating receipt pair.

**Proven in a pre-registered install hearing** (Phase-0 perimeter): legs L1–L8 and claims F1–F8 all PASS — planted pin-mismatch and out-of-scope refusals in their exact states, a gate decline stopping an install, byte-equal rollback. Full record: `docs/evidence/foundry-install-hearing/`.

**Grades, on their faces:** registry bindings are test-grade until the registrar custody act; the decision chain is consistency-grade under the development signer. Measured runs (RUN-5, RUN-7) remain attributed to the v1.1.0 tree; the install hearing ran on v1.2.0. 273 tests pass; ruff and mypy clean; receipts for the eight shipped act classes are byte-identical under frame v2.

## [1.1.0] — 2026-11-02

Everything below is labeled with the verification it actually carries. Features are not measurements; where a number appears, it names its own evidence.

- **The supervisor — `chancellor supervise` (the KEEP office).** Continuity is now a product capability, not external scaffolding: the supervisor watches the governed agent's signed checkpoint boundary, discriminates dead from stalled, verifies the chain at the newest signed checkpoint **before** any resume (verify-or-halt — resume is never forced), resumes with a provisional window, and writes signed interruption receipts with the cause graded proven / plausible / unknown — never fabricated. Its escalation budget survives its own restarts, rebuilt by replaying its own signed log. *Verification:* fault-injection verified — a supervised agent SIGKILLed mid-work is detected, verified, and resumed to completion with a proven-cause receipt, and a corrupted chain is refused with the agent never relaunched: **15 / 15 consecutive fault-injection pairs** on the final tree, plus the same pair run against the installed package binary. (The earlier measured runs predate the supervisor and do not claim it; its own evidence run is a separate instrument.)
- **Checkpoint v2 — the anchor commits to the count.** Receipts now build checkpoints on an RFC 9162 Merkle tree, and one anchor digest commits to root + log size + head together — closing an anchor-layer gap where a bare root could not distinguish a log from itself-plus-a-duplicate. v1 records still verify under v1 rules. *Verification:* the test suite's checkpoint-v2 cases, and regression — the v1 sample evidence and the judging soak's published snapshot both verify under the new verifier.
- **Test runs are records.** Freeze manifests and test-run results are first-class entries in the same hash-chained log, resolvable by a fail-closed `resolve` verb — a release's test proof is part of the receipt book, not a claim beside it.
- **Receipts name their frame; refusals leave receipts.** Every new receipt and gate verdict is stamped, inside the signed payload, with the governing frame it was decided under (`e5.chancellor_frame.v1`, schema `e5.decision_receipt.v2`; v1 entries are pre-frame legacy and verify as such). Every gate refusal is receipted with a named refusal state — a refusal is never a silent absence.
- **Design only — labeled as such, not built:** the Suite C adversarial admission exam ([docs/suite-c-design.md](docs/suite-c-design.md)), the cap object for the human gate ([docs/cap-object-spec.md](docs/cap-object-spec.md)), and production signer separation ([docs/signer-separation-design.md](docs/signer-separation-design.md)) ship as design documents. A further specification in the repository specifies capability install — an agent gaining a new capability as a gated, receipted, reversible act under the same frame — written against governed install machinery already running in the entrant's wider multi-agent programme, where its doc-only perimeter is admitted on measured evidence. They change no behavior and claim none.

## [1.0.0] — 2026-11-01

Hackathon submission build — Meta Global AI Developer Hackathon (Cerebral Valley), Indie track.

**Results:** Suite B reliability frontier at 10x — governed drift 0/1,800 vs 300/1,800 ungoverned (95% upper bound 0.166% cell-level, n=1,800; 25.9% manifest-level, 0 of 10); value-cell extension 0/2,000; four 8-hour soaks, 1,846 audit-chain entries re-derived, 0 breaks. Evidence: `docs/evidence/run-5/`.

**Demo:** the film is linked in the README Demo section; `chancellor demo` reproduces the hearing offline, no key required.

**Honest negative:** the Suite A judge-calibration gate has not passed (calibration of record and one pre-registered remedy both failed their gates); no Suite A score is claimed. See BUILD-LOG.md.
