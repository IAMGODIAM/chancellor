# FILM-MOTION PROTOCOL — the motion crew, absorbed
## Wisdom Council on the Product Machines · filed 2026-11-04 (companion to COUNCIL-RECORD.md)

The film-side yield of the Teardown Absorption: what the house film lanes (demo films, machine films, cutdowns) now carry that they did not. Everything here is bespoke or instruction-layer — mechanisms and doctrine recovered from the named artifacts and rebuilt in the house shape; no stack is imported. Items are numbered FM-1–FM-5 for citation. The governing workflow, confirmed against house practice by the recon: *reference → storyboard → animate → score → render → inspect → cut again* — the house already ran most of it; this protocol fills the three genuine gaps (reference measurement, procedural score, the formalized inspect loop) and sharpens the rest.

## FM-1 — Reference measurement (from #01, sub-level/marketing-videos — the method, not the stack)

Before a film's motion is designed, its reference is **measured frame by frame**: move durations in frames, cap heights, per-element arrival frames, easing shapes read off the reference's own motion. The discipline in the source's own words, adopted as the lane's test: *if you cannot describe the move in a sentence that contains numbers, you have not finished measuring.* This is the house's firsthand-verification doctrine applied to film grammar — the film analogue of TA-5's reference-first rule. **Not taken:** the source's stack (Remotion scaffold, Higgsfield AI-footage MCP, Epidemic Sound) — paid/external lanes the $0/owned-infra doctrine does not need; the scaffold is not imported.

## FM-2 — The review loop as standing protocol (from #09, whaleyxbt/claude-motion — inside the gate, not instead of it)

Every film, every lane, runs the loop as protocol: **draft render → contact sheet (one timestamped frame per beat) → written checklist (collisions, clipping, holds, safe area, phone readability) → zoom/scrub the doubtful transitions → fix in the parameters → re-render → repeat**, closing with the sheet of the *encoded* file (BUILD-PROTOCOL TA-7 carries the same rule machine-side). The loop's maxim is adopted verbatim as lane law: **never report a video as done without looking at contact sheets of the current render.** Enforcement is unchanged and is the house's addition: the loop runs **inside the design gate** — independent, fail-closed, receipted. The loop is the procedure; the gate is the authority. (Tonight's demo cut ran this discipline artisanally — frames extracted from the delivered MP4, read firsthand, claims audited; FM-2 makes it standing rather than heroic.)

## FM-3 — The procedural score lane (ONE mechanism — Lane A #5 × #09's `sfx/` engine, merged by adjudication)

The house gains the crew member it lacked: **procedural sound, composed in code from the film's own timeline.**

- *Engine:* bespoke, **pure Python stdlib** — synthesis, mixing, and a genuine ITU-R BS.1770 loudness implementation (K-weighting, gated integrated loudness, true-peak). No samples, no licences, no dependencies; $0 and owned, the house shape. (Recorded samples, if ever used, carry documented provenance, as the source's CC0 set does.)
- *Composition:* cues are placed from the machine/film model itself — a thump on every power stroke, a click on every button press — computed from the same event list that drives the picture.
- ***One timeline JSON is the single source:*** the steps table / beat plan is serialized once and read by **both** the picture and the score. This is the council's deliberate correction of the source artifact: teardown's score *hand-mirrors* its film's beats (its timeline.json holds only a duration) — disciplined mirroring, and a drift risk of exactly the kind its own doctrine warns against. The house lane shares data, not copies.
- *Mastering:* −14 LUFS integrated (BS.1770, implemented, not estimated); the delivered file's waveform + loudness are read back off the encoded artifact (the `wave.mjs` lesson: measure what you will actually post). Peak ceiling: the sources disagree (−1 vs −2 dBFS); the council's interim ceiling is the stricter **−2 dBFS**, flagged as our choice until the lane's first build measures its own.
- *Scope:* machine films first (they are silent today), then all film lanes. Narration lanes (ElevenLabs/Eli) are untouched — the score lane is the music/SFX crew, not the voice.

## FM-4 — Instruction layers adopted (doctrine and craft text; zero new runtime unless noted)

- **#02 — LottieFiles/motion-design-skill → all film lanes.** The meaning layer: duration/easing tables, Disney's 12 principles adapted for interface motion, emotion-to-motion mapping, choreography, quality rules. Philosophy-first and engine-agnostic; it names what our art-pass critic previously supplied ad hoc. Timing/easing parameters enter builds as *starting values* re-derived against the house register (with TA-6 machine-side).
- **#03 — iart-ai/motion-design-skills → two skills only: `shot-composition` + `motion-art-direction`** (demo films + machine films). Grids, safe areas, focal hierarchy, camera-move plans *with numbers*, cross-aspect adaptation; motion language, pacing, hierarchy, restraint. Adjacent value noted: beat-sync-editing; color-motion (OKLCH interpolation — adjacent to our sRGB lesson). **Caveat carried wherever cited: iart is a commercial funnel** (README routes to a paid agent); the skills are MIT and stand alone — the house takes the craft, not the funnel, and follows no link.
- **#05 — iart-ai/kinetic-typography-skills → demo films.** The beat-carrying type craft: character/word/line staggers, split-text reveals, variable-font weight transitions, text on a path, title/interruption cards. This is "huge words interrupt the story at exactly the right moment" as a technique set; the demo cut's typeset supers are its first upgrade target.
- **#06 — greensock/gsap-skills → the instruction layer for the vendored GSAP.** The library is already house property (the 157,715 B motion kit, vendored); what is adopted is the official instruction layer that teaches an agent to choreograph with it correctly — gsap-timeline above all, plus ScrollTrigger, plugins (SplitText/MorphSVG now free with GSAP), and the performance rules. Zero new runtime, zero licence change. The cheapest adoption in the set.
- **#10 — iart-ai/tiktok-video-skills → NARROW adoption: the cutdown lane only.** short-form-video grammar (hook → retention → loop, pattern interrupts, pacing for 9:16) and caption-animation (word-timed karaoke captions from a transcript) — for cutdowns of the demo and machine films to social surfaces. The core lanes remain 3:00 demonstrations; nothing in the core is re-cut to Shorts grammar by this adoption.

## FM-5 — WATCH items (no adoption; preconditions stated)

- **#07 — remotion-dev/skills (Remotion).** A different composition stack (React components through headless Chromium), not a better render conscience; the house lane (HTML/HyperFrames + Blender frame sequences → ffmpeg) is proven and shipped. **Preconditions to any future adoption, both required:** (1) a **licensing read** — the API returned no licence for the skills repo and the Remotion core carries a custom licence (NOASSERTION); the question is answered from the licence text, not from summaries; (2) a **council stack comparison** — Remotion against the proven house lane on a real commission, judged on output, cost, and determinism. Until both are run, the skills may be *mined for practice* (render/caption craft) without the stack being adopted.
- **#08 — haidrrrry/claude-remotion-skill.** Method portable, stack gated on #07: if Remotion is ever adopted, #08 is re-examined as its craft layer; until then its genuine content — the mandatory render → inspect → fix loop — is already covered by FM-2 (the stronger, stack-closer #09 form) plus gate practice. Recorded flag: the same author's catalogue contains unrelated tools the house does not adopt; the council adopts artifacts, never authors wholesale.

---

## DELTA AMENDMENTS — 2026-11-04 (Motion Delta confirmation sitting)

Filed by the Delta Confirmation sitting of the same council (Leonardo presiding), adjudicating RECON-MOTION-DELTA.md's eight draft grades against this protocol as filed. Full record: DELTA-RECORD.md. **The protocol's numbering extends to FM-6.** FM-1–FM-5 as filed are unaltered in text and unrenumbered; the amendments below are additions.

### FM-1 addendum — remake mode, the named stronger form (from Δ-03, howseen-ai/claude-motion-design)

FM-1 measures a reference's grammar. Its stronger form is named **remake mode**: a frame-locked 1:1 remake pipeline — extract every frame of the reference → detect its cuts → write a shot-by-shot specification → rebuild the film under a new brand, judged on side-by-side compare sheets. Remake mode **never reuses the reference's music, voice, or people**; it reconstructs structure, not assets. It is measurement carried to full reconstruction, and it enters a build only where a commission names it — FM-1's measure-first discipline remains the default.

### FM-2 addendum — encode-QC clauses (from Δ-03)

The review loop's checklist gains two encode-level checks, run on the encoded file (the TA-7 surface):

- **Pop / flash detection** — scan for audio pops and one-frame flashes at cuts and joins; a hit is a defect fixed in the parameters, not a note.
- **Loop-seam check, in position and velocity** — where a film loops, the seam must match in where every element *is* and in how fast it is *moving*; a position match with a velocity jump is a failed seam.

### FM-4 addendum — two instruction layers (from Δ-02, charlie947/motion-graphics-skills)

- **Brand-intake constitution** — before a brand's first film, and read before every later one, the lane keeps a persistent per-brand constitution: `brand.md` (the brand's identity facts) + `MOTION.md` (how this brand moves — easing temperament, chart behaviour, pacing, reel grammar). This is the layer FM-4 lacked: the Canon and the design registers state the *house's* law for surfaces; the constitution translates a *specific brand's* identity into motion parameters a build can read. **Subordination (the council's clause, DELTA-RECORD T-2):** a brand constitution is a working file, subordinate to the Creative Canon and the design registers — where one conflicts with the Canon, the Canon governs and the constitution is corrected.
- **Values-exact animated-chart** — data graphics under the source's rule, adopted verbatim as lane law: *every value stays exactly as you give it.* The evidence-film discipline (figures copied character-for-character, bounds beside zeros) applied to animated charts: a chart animates the given values; it never rounds, smooths, or re-scales them into a better story.

### FM-6 — The footage branch: editing and treating supplied recordings (from Δ-04 + Δ-05)

FM-1–FM-5 govern films the house *generates*. FM-6 governs films the house *receives* — supplied recordings are a standing input class (the vision-series intake, transcribed and normalized by hand; supplied recordings feeding campaign and presenter work), processed without an edit discipline until this branch (DELTA-RECORD T-1; claim routed as D-1). The branch runs on the house stack (HyperFrames + GSAP); its loop is FM-2's, its gate the house gate. Its scale is episodic by design — a branch, exercised when recordings arrive.

- **Edit discipline (Δ-04, inematds/hyperframes-student-kit — the kit's local path only):** transcribe (Whisper local, or ElevenLabs Scribe — the house's existing lane, no new dependency) → **cut-silences** → **cut-mistakes** (proposed error cuts are *shown for review* before they are taken — no silent deletion) → edit-decision-list review → beat-sync validation → preflight. Verify-in-cycle: each stage's output is inspected before the next consumes it.
- **Treatment (Δ-05, Barty-Bart/motion-graphics):** **motion-broll** — motion-graphic B-roll generated from the footage plus its transcript, timed to the speaker's words; **object-separation** — a person, product, or hand separated from its background, locally.
- **REFUSED on this branch's face:** **Kie.ai** (paid AI video/image generation) and the **Kling AI subscription** — external paid generation lanes; they are not dependencies of this branch in any form, default-adjacent or otherwise. The branch's generation is the house's own (owned models, owned stack).

---

## ABSORPTION LEDGER — every item, where it now lives

| Item | Disposition | Lives at |
|---|---|---|
| A-1 Model-first law | ADOPT (confirmed) | BUILD-PROTOCOL **TA-1** |
| A-2 Interactive simulator tier | ADAPT (confirmed) | BUILD-PROTOCOL **TA-2** (build class) |
| A-3 render(t) purity + seeked capture | ADAPT (confirmed) | BUILD-PROTOCOL **TA-8** |
| A-4 Critic stills loop | ADOPT (confirmed) | BUILD-PROTOCOL **TA-6** (§8 amended) |
| A-4b Post-encode sheet of the delivered mp4 | ADOPT (confirmed) | BUILD-PROTOCOL **TA-7** (§8 amended); FM-2 closing step |
| A-5 Procedural score | ADAPT (**amended** — merged, one-timeline rule) | **FM-3** (single mechanism with B-09 sound) |
| A-6 Quality tiers + shader warm-up | ADOPT (confirmed) | BUILD-PROTOCOL **TA-4** |
| A-7 Sub-1 MB page discipline | ADOPT (confirmed) | BUILD-PROTOCOL **TA-2** (page discipline) |
| A-8 Reference-first rule | ADOPT (confirmed) | BUILD-PROTOCOL **TA-5**; FM-1 (film form) |
| A-9 Timing/taste numerics | ADAPT (confirmed) | BUILD-PROTOCOL **TA-6(c)**; FM-4 (#02 parameters) |
| A-10 Break-it slider | ADAPT (confirmed) | BUILD-PROTOCOL **TA-3** (inside TA-2) |
| A-11 Wholesale kit import | **REFUSED** — bespoke rule; ancestor baggage; root data-model mismatch | COUNCIL-RECORD §3 (refusal of record) |
| A-12 Pale-studio look | **REFUSED** — Canon governs house surfaces | COUNCIL-RECORD §3; TA-2 register clause |
| A-13 Prompt-first workflow | **REFUSED** — plan-first doctrine | COUNCIL-RECORD §3 |
| B-01 Reference measurement (marketing-videos) | ADOPT, method only (stack refused) | **FM-1** |
| B-02 Motion-design doctrine (LottieFiles) | ADOPT | **FM-4** |
| B-03 Shot skills (iart, two skills; funnel caveat) | ADOPT (narrowed to two skills) | **FM-4** |
| B-04 ai-design-skills (elayadesign) | **REFUSED** — brief does not match the artifact (no motion skill ships) | COUNCIL-RECORD §4; CLAIMS.md C-3 |
| B-05 Kinetic typography (iart) | ADOPT | **FM-4** |
| B-06 GSAP skills (GreenSock) | ADOPT, instruction layer only | **FM-4** |
| B-07 Remotion skills | **WATCH** — licensing read + council stack comparison required | **FM-5** |
| B-08 claude-remotion-skill (haidrrrry) | **WATCH** — gated on B-07; loop already covered | **FM-5** (loop at FM-2) |
| B-09 claude-motion: sound engine | ADOPT (**amended** — merged into the one score lane) | **FM-3** (with A-5) |
| B-09 claude-motion: review loop | ADOPT (**amended** — protocol inside the gate, not a replacement) | **FM-2**; TA-6/TA-7 |
| B-09 claude-motion: web-sims architecture | ADOPT (same mechanism as A-3, one adoption) | BUILD-PROTOCOL **TA-8** / TA-2 |
| B-10 TikTok skills (iart) | ADOPT, narrow (cutdowns only) | **FM-4** |
| Δ-01 product-launch-motion (#1, second list) | **WATCH** — split resolution (AbubakrChan vs ouerf-man); conditional recorded, not settled by vote | DELTA-RECORD §1 (T-3) / §2 |
| Δ-02 motion-graphics-skills, charlie947 (#2) | ADOPT, narrow (**amended** — Canon-subordination clause) | **FM-4 addendum** (Delta Amendments) |
| Δ-03 claude-motion-design, howseen-ai (#3) | ADOPT, narrow (stock-download lanes not adopted) | **FM-1 addendum** (remake mode) · **FM-2 addendum** (encode-QC) |
| Δ-04 hyperframes-student-kit, inematds (#4) | ADOPT, edit discipline (local path only); **Kie.ai + Kling AI REFUSED** | **FM-6** (refusals on its face) |
| Δ-05 motion-graphics, Barty-Bart (#5) | ADOPT, narrow (treatment; sound-effects + explainer trio not adopted) | **FM-6** |
| Δ-06 animate, cth9191 (#6) | **WATCH** — council stack comparison + a real animated-shorts commission required | FM-5 pattern; mined practice pointers at DELTA-RECORD §2 |
| Δ-09 Motion library, motiondivision (#9) | **WATCH** — web-lane stack item, not a film item | **Web lane's ledger** (recorded here for delta completeness) |
| Δ-10 motion-dev-animations-skill (#10) | **WATCH** — paired with Δ-09; verify checklist citable without adoption | **Web lane's ledger**; checklist at DELTA-RECORD §2 |

*Ledger closed. 23 adjudicated items: 21 confirmed, 2 amended (A-5, B-09 — both amendments are convergences into single mechanisms), 0 overturned; 4 refusals of record (A-11, A-12, A-13, B-04); 2 items on watch with named preconditions (B-07, B-08). **Extended by the Delta Confirmation sitting (2026-11-04):** 8 further items (Δ-numbering follows the second share's list) — 7 confirmed, 1 amended (Δ-02, the subordination clause), 0 overturned; 2 refusals added on FM-6's face (Kie.ai, Kling AI); 3 items on watch (Δ-01 with its conditional carried open; Δ-06 behind the FM-5 gate); the web-lane pair (Δ-09, Δ-10) is recorded here but belongs to the web lane's ledger. Combined record across both sittings: 31 items.*

---

## Reconciliation addendum — independent second review (2026-11-04)
Operative clauses from RECONCILIATION-2ND-REVIEW.md (this folder), against the Chancellor desk's independent VET of the same lists:
- **FM-5 (Remotion branch):** the licensing read is discharged with findings — #12 carries the custom entity-tiered Remotion License; **#13 has no license file and cannot lawfully be vendored or adapted**. The branch is **PASS for absorption, closed**; re-opening requires a named need + a fresh license answer. #8 (claude-remotion-skill) moves WATCH → PASS with the branch.
- **FM-6 (footage branch):** source of record pinned by provenance — **nateherkai/herk-edit-kit** (Nate Herk; formerly the HyperFrames Student Kit). Standing clause: no material from a license-flagged repo (#4/#5 NOASSERTION) is vendored until the full license text is re-read and the re-read filed.
- **FM-4:** HyperFrames, the house assembly lane, is **Apache-2.0** (heygen-com/hyperframes) — recorded. #2's pack-level disposition is WATCH; its two mechanisms stand adopted as techniques.
