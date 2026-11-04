# TREATMENT-B — Beat 3, "The Supervisor Working" · Design Swing B

**Segment:** 28.00 s · 1920×1080 · 30 fps · audio = v1 Beat 3 stem (27.68 s, laid at 0.00).
**Scene cuts are placed in the stem's measured pauses** (ffmpeg silencedetect, −38 dB):
speech 0–1.75 · 2.31–4.10 · 4.50–5.93 · 6.43–10.03 · 10.45–16.88 · 17.43–19.18 ·
19.70–23.73 · 24.29–27.68. Every cut lands inside a pause; no word is ever cut across.

## The system (scales to all six beats unchanged)

**One world, one camera.** The whole film lives on a single ink stage — the
Chancellor's desk: a navy radial glow upper-left, a receipt-chain horizon running
the bottom third, a hairline gold frame inset 48 px. Scenes never hard-swap the
world; the *camera* (GSAP scale/translate on the world group) moves attention
before the scene changes — push-in to the console, snap to the heartbeat strip,
pull-back as the book builds, dead still at the refusal (stillness = meaning),
slow settle at the close.

**The Sentinel — the element you follow.** A 54 px gold ring with a sapphire
core: KEEP's eye. It pulses over the console while the watch holds, darts to the
break point when the kill lands, walks the chain card-to-card as receipts land,
and comes to rest at the centre of the refusal stamp. One character, every beat:
in Beat 2 it watches the gate; in Beat 4 it rides the counter; in Beat 5 it
shelves the records.

**Finish language.** Panels: midnight navy at 82% over ink, 28 px radius, 1 px
gold hairline, soft 40 px shadow. Chips: full-pill, letterspaced small caps.
Stamps: 18 px radius, 2 px edge, −2° seat. Type: serif display (Bodoni-class)
for the huge interruptions, Inter for labels, monospace for all evidence —
evidence is never set in a proportional face. Palette: ink `#0a0a0e`, ivory
`#f5efe1`, gold `#c9a84c`, navy `#0b1f3a`; ruby `#a31621` reserved for fault and
refusal; emerald only on a *verified* tick; **champagne `#ecd9a4` appears
exactly once per beat** — here, the seal ring around the refusal stamp.

**Easing table (FM-1 — every move describable in numbers).** Entrances:
power2.out, 0.45–0.50 s, 40 px rise. Stamps: back.out(2.0), 0.28 s, scale
1.6→1. Type-on: 12 ms/char stagger. Camera push: power2.inOut across the
scene's full length, 1.00→1.05. The NO: expo.out, 0.22 s, scale 2.2→1.
Dim: power1.inOut, 0.6 s to 35% brightness. Count-up: power1.out, 0.8 s.
Settles: power3.out, 0.7–0.8 s. Nothing moves without a reason in this table.

## The beat, scene by scene

- **S0 · 0.00–2.31 — the hook.** A single gold chain link draws itself
  (stroke-dash, 18 f). "KEEPING THE RECEIPTS" staggers in word-by-word
  (0 / 0.35 / 0.70 s, 92 px serif ivory); "IS HALF OF IT." lands in gold small
  caps. As the voice ends (1.75) the title lifts and shrinks to the top bar
  (scale →0.22, 0.5 s power3.inOut) — the camera's attention move, not a cut.
- **S1 · 2.31–6.43 — the watch.** Console card rises; the real supervise
  output types on verbatim (`[supervise] anchoring: Tier A — …`); chips carry
  the seq-0 values (`budget 3` · `stale threshold 180s` · `tier_a_same_machine`);
  the exhibit's real pass line appears (`gather → total 87.5 — pass`). The
  Sentinel pulses at the card's corner (1.2 s sine). At "it watches the run
  itself" (4.50) one gold scan-line sweeps the card. Camera pushes 1.00→1.05.
- **S2 · 6.43–10.45 — the kill.** Snap (6 f) to the heartbeat strip: a gold
  pulse line draws steady under `AGENT PROCESS — LIVE`. At 8.55, mid-"catches
  it": one ruby frame at 18%, the line flatlines, the field chip `exit_status
  −9` drops. Three stamps slam in sequence (0.28 s each): `INTERRUPTION
  DETECTED` · `CAUSE: PROVEN` · `WITNESSED ✓` — seq-1's verbatim values. The
  Sentinel darts to the break (0.4 s power3.in). The real console line runs
  the full width below, unabridged.
- **S3 · 10.45–17.43 — the proof.** The book builds: the supervision log's
  four receipts chain in left→right (landings 10.6 / 12.0 / 13.4 / 14.8), each
  card carrying its seq, its action line verbatim, and its `entry_hash` first
  8 (`1ee5dc78 · 3cbea310 · 22e41d56 · 698c85be`) on the gold links. Seq-2 —
  chain verification FAILED — takes the ruby edge and its own rationale line.
  At "twenty-two of twenty-two" (13.96) the numerals count 0→22 / 22 in
  120 px gold serif: *every kill fired — detected and receipted* (measured
  trial, RUN-9 register). The Sentinel walks the chain with the landings.
- **S4 · 17.43–24.29 — the refusal.** The world dims to 35%. Stillness. At
  "saying no" (19.18): **NO.** — 340 px ivory serif, expo.out slam, camera
  dead still. Under it the refusal receipt rises (0.7 s power3.out): the
  book's seq-3 instrument, fields verbatim — action *Send the proposal to the
  stakeholder list* · `external_send` · `publish` · `approved: False` ·
  `decider: policy` · rationale *human gate with no approver attached —
  denied (fail-closed)* · `cost_usd: null`. Last, `refusal_state:
  no-approver-attached` stamps in ruby, and the beat's one champagne mark —
  a thin seal ring — closes around it. The scripted super sits below:
  `refusal receipt — no-approver-attached · budget not decremented`.
- **S5 · 24.29–28.00 — the unmoved budget.** Attention pans (0.8 s) to the
  persistent budget chip, present since S1, pixel-identical all along:
  `BUDGET · COST BOOKED $0.00`. It opens into the ledger: seq 0–3, each
  `cost_usd: null` verbatim, total `BOOKED — $0.00`. The number animates
  *nothing* for a held 2.5 s — the stillness is the claim. Gold frame
  brightens once; fade to ink at 27.7. Head/tail frames rest-state, ready
  for the joins either side.

## Evidence discipline

Every string of evidence is copied character-for-character from
`captures/beat3v2-sup-console.txt`, `captures/beat3v2-supervision-log.jsonl`,
and the refusal receipt in `captures/beat2-audit-log.jsonl` seq 3 (the
production log's designated refusal receipt). Packaging invents layout,
motion, and metaphor — never a value, a field, or an output line.
