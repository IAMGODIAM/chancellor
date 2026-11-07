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

## [1.2.3] — 2026-11-05

The rectification release: **the 1.2.2 source distribution shipped its test suite without files the suite requires, so the suite could not run from the downloaded artifact at all. 1.2.3 makes the source artifact self-testing.** No product behavior changes on any shipped path, and the hackathon submission is untouched — the portal record stands on 1.2.2 exactly as submitted. This release corrects the public download, not the entry.

- **What was wrong.** The 1.2.2 sdist included `tests/` but omitted `tools/` in full — the tree shipped no `MANIFEST.in`, so setuptools' default file list decided — and also omitted `docs/governance-frame.md`, the `docs/evidence/` tree, and the fixture `tests/fixtures/installs/eight-class-golden.jsonl`. Each of those is read by tests that did ship: the release-sync test loads the tooling by path and copies the whole `tools/` tree; the frame-receipts and installs tests read the frame document, the filed evidence, and the fixture. Run from the unpacked artifact, the suite died at collection (`FileNotFoundError: tools/release_sync.py`) and not one test could run. The defect was found by running the shipped suite from the published artifact itself (the full-product test on a clean machine) and confirmed against the tarball PyPI serves.
- **The cure — the measured set, nothing more.** A new `MANIFEST.in` ships exactly the files the shipped tests read — `tools/`, `docs/evidence/`, `docs/governance-frame.md`, and the one fixture — with the reason written into the file. The rest of `docs/`, which no shipped test reads, stays out. Verified before publication from the artifact itself: the sdist built from this tree, unpacked into a clean directory, runs its own shipped suite end to end.
- **The exhibit names its seal.** The headless demo's audit log verifies only with its signed-checkpoint sidecar beside it; lifted alone it reads NOT VERIFIED, and the exhibit — which presents the log as the book — named only a state directory, not the second file. Beat 4 now prints where the seal lives and that the log alone reads NOT VERIFIED (no_checkpoint). The demo already sealed its book at every size; only the label was missing. No behavior change.
- **The version test measures its own precondition.** The leg that asserts the version fallback requires an environment with no chancellor distribution installed; where one is installed, the leg now skips and names the version it found, instead of failing on an environment it does not control. In an uninstalled environment the original probe and assertion run unchanged.
- **Release-machinery hardening.** The version-literal gate's exemptions are now scoped to the exact span each exemption matches rather than the whole line, so an unrelated literal sharing a line with an exempt tool version can no longer pass unclassified. Three production-kit literals are classified as what they are — tool versions (the film renderer, the animation library) — not product versions; no literal was edited to make a check pass.

The suite stands at **297 passing** — the same 297 as 1.2.2, now runnable from the source artifact itself — with Ruff format and lint at zero findings and mypy clean.

**Calibration posture unchanged:** judge verdicts remain labeled *uncalibrated* under the interim calibration rule, exactly as in 1.2.2. Signatures remain tamper-evidence under the development signer, not non-repudiation, as documented.

## [1.2.2] — 2026-11-03

The release-machinery release: **release-sync tooling and the drift watch ship; the product does not change.** No behavior change on any shipped path, no new surface, no second-seat code (that is its own later release). What changes is how releases are made and watched, so the failure that shipped 1.2.0 carrying the previous release's PyPI page (F-CUE-001, found by an outside reader) cannot recur silently.

- **One declaration.** The version lives in exactly one place — `pyproject.toml`, `[project] version`. `chancellor.__version__` derives from it (installed metadata, else the pyproject beside the source tree, else an honest `0.0.0+unknown` sentinel) and is never a typed literal again. The test count is computed from a green suite run's JUnit XML (passing = tests − failures − errors − skipped), never typed.
- **Generated surfaces, machine-checked.** The README's status line, tests line, badge alts, and current "What's new" heading, plus `CITATION.cff` and both badge SVGs, are generated from the declaration and the computed count by `tools/release_sync.py render` — marker regions in prose files, templates for whole files. `tools/release_surfaces.toml` is the manifest that draws the line between living surfaces and the record; historical text is exempt there by name and is never rewritten.
- **A fail-closed gate in the publish path.** `publish.yml` runs Gate A on the exact tagged tree before anything builds (tag ↔ declaration, derived surfaces current, changelog head, fresh suite count, the version-literal scan, the dispatch guard) and Gate B on the built wheel and sdist before the upload. A red gate stops the release; there is no override. Manual dispatch is guarded to a tag naming the expected version.
- **A drift watch on the served side.** A standing loop compares the served PyPI page against the latest release's tag tree daily and speaks only on drift; its loop contract (CONTRACTED under Loop-Contract Spec v0.1) and ledger live with the release machinery. Its first live cycle, run against 1.2.1 after that release, read `in_sync` on every surface.
- **This changelog exists.** `CHANGELOG.md` was created by the migration (entries for 1.2.1 and earlier assembled from those releases' own words, per the migration note above); from this release on, the gate binds its head entry to the declaration.

The suite stands at **297 passing** — the 287 of 1.2.1 plus the release-sync tool's own 10 — with Ruff format and lint at zero findings and mypy clean, identical commands in pre-commit and CI.

**Calibration posture unchanged:** judge verdicts remain labeled *uncalibrated* under the interim calibration rule, exactly as in 1.2.1. Signatures remain tamper-evidence under the development signer, not non-repudiation, as documented.

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
