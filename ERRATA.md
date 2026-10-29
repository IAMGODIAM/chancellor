# Errata

Corrections to documents that are frozen or already published. The frozen
text is never edited in place; the correction lives here and governs.

## E-1 — "Muse Wonder Full" is not an API model (2026-10-29)

**Where the error stands:** the frozen SPEC (architecture diagram; the
SPEC is available in the submission packet and is not part of this
repo) lists the client tier as "Muse Spark · Muse Wonder / Wonder
Full · …", and early pitch copy echoed it.

**The correction:** `muse-wonder-full` does not exist as a model on the
Meta Model API. "Wonder Full" is a tier of the Muse *consumer
subscription*, reachable only inside the Muse product on paid plans —
it cannot be called through the API at any price. Any text that presents
it as an API-called tier is wrong.

**What governs instead:** the model column admits only exact, versioned
model IDs (Council AM-5), enforced in code in
`src/warden/api_client.py` (`MODEL_IDS`, with a test asserting the
nonexistent constant is absent):

- `muse-spark-1.3` (+ `muse-spark-1.3-contributor`)
- `muse-wonder-1.0`
- `muse-image-1.0`
- `sam-3.1`
- `meta/muse-glimmer-30b` (NVIDIA dev/overflow lane — a real Muse-family
  model, hosted by NVIDIA, not part of the Meta Model API column)

**Scope:** this erratum corrects the README, the demo, and all submission
surfaces. The SPEC file itself remains frozen, unedited, as the record of
what was planned; this file is the pointer that travels with it.
