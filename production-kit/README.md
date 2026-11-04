# production-kit

The reusable production machinery from the Chancellor submission week
(2026-11-04), posted as it ran. Two crafts: **film** — how the week's films
were designed, composed, scored, and reviewed — and **deploy** — how the
programme's pages and films got onto their own domain. Everything here is
text; the binary assets the film sources reference are dependencies and are
noted as such below.

## Contents

| File | What it is | Proven in |
|---|---|---|
| `FILM-MOTION-PROTOCOL.md` | The house film-motion doctrine, absorbed 2026-11-04: FM-1 reference measurement, FM-2 the review loop as standing protocol, FM-3 the one procedural score lane, FM-4 instruction layers, FM-5 the Remotion branch (closed), FM-6 the footage branch. | Every film lane of the week — the demo cut and the three machine pull-aparts ran under it. |
| `TREATMENT-B.md` | Swing B's design treatment for Beat 3, "The Supervisor Working": one ink stage, the Sentinel, the finish language, an easing table with numbers, scene-by-scene direction, evidence discipline. | The bake-off of 2026-11-04 — B won and its system re-skinned all six beats of DEMO-CUT v3 (180.000 s, exactly). |
| `beat3/` | The HyperFrames composition sources for that beat: `index.html` (the composition), `hyperframes.json`, `meta.json`, `package.json`. | Rendered with HyperFrames 0.8.45 on a Lambda A10 box; the full-film version of this composition is Beat 3 of DEMO-CUT v3. |
| `score.py` | The FM-3 procedural score engine: pure Python stdlib synthesis with an in-engine ITU-R BS.1770 loudness implementation. Bed and cue stems are balanced by measurement against a target, never by ear. | The B treatment of the Sealing Desk pull-apart: score composed from the film's own 87 explode steps; delivered film read back at −14.18 LUFS. |
| `timeline.json` | The single timeline both crafts read — the picture builder and `score.py` consume the same file (acts, the 87 authored explode steps out and home, the break, the cues). One timeline, no hand-mirrored copies. | Same film: 720/720 frames present and unaltered inside the treated cut. |
| `deploy_pages.py` | Direct-upload deployment to a Cloudflare Pages project with no git source: upload-token → check-missing → batched base64 upload → upsert-hashes → deployment, manifest built from blake3 hashes of the file bytes. | The custom-domain execution of 2026-11-04: the landing, the Board, and both dashboards went live on `iamgodiam.net` addresses through this script, after the asset-blob blocker that stranded the first launch-night attempt was cured by this protocol. |

## Using the deploy script

```
CF_ACCOUNT_ID=<account id> python3 deploy_pages.py PROJECT served_path=local_file [served_path=local_file ...]
```

The account identifier is read from the `CF_ACCOUNT_ID` environment variable
and exists nowhere in the file; with the variable unset the script refuses to
run. Real credentials are fetched at runtime through the lane's credential
mechanism and the upload JWT is held in memory only — nothing is embedded,
printed, or persisted.

## Two operational lessons (paid for once, recorded here)

1. **Pages refuses any single file over 25 MiB.** The 38.2 MiB demo film
   cannot ride the Pages lane, and the verified bytes are never split or
   transcoded to force a fit. Big films are served from **R2 behind the same
   domain**: a small Worker routed on `/film/*` answers from a bucket holding
   the byte-identical file, so `chancellor.iamgodiam.net/film/DEMO-CUT-v3.mp4`
   is the film itself (range requests included) while Pages keeps every
   other path.
2. **A full-set deploy must hash-verify every carried file immediately
   before firing.** During this week's deployments, a sibling lane's newer
   export overwrote the shared export path mid-run and a gate-failed build
   rode one deployment. The hash check against the deployment record caught
   it in the same run and the gated bytes were restored byte-exact — but the
   pre-flight hash was taken at lane start, and that gap is the lesson:
   verify at fire time, not at start time.

## Dependencies referenced, not included

`beat3/index.html` references binary assets by path under `beat3/assets/` in
the production tree: three fonts (`BodoniModa.ttf`, `Inter.ttf`,
`SourceSerif4.ttf`) and the beat's stem audio (`beat3-stem.mp3`). They are
dependencies of the composition, not contents of this kit — and one of them,
`SourceSerif4.ttf` at ~1.2 MB, exceeds the contents API's per-file limit,
which is a further reason they travel with the production tree rather than
being posted here.
