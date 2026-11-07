# Cold Verifier Report — Foundry Install Hearing (F7 / F8 spot-check / F5 fold recount)

Verifier posture: cold. The verifier ran nothing in the hearing. All checks below were run in fresh
Python processes from a scratch cwd (`/tmp/coldverify`), read-only against the filed inputs.
Only this report and `cold-verifier-verdict.json` beside it were written.
No key material from `issuer-keys.json` is reproduced here; that file is referred to by name only.

Date of verification run: 2026-11-02 (session time).

---

## Check 1 — Product verifier over the hearing chain (F7)

- Verifier: shipped product code, `chancellor.verify_log` from
  `/home/hatch/workspace/hackathon-2026/scratch/foundry-build/repo/src`
  (run both as the module CLI `python3 -m chancellor.verify_log` and via the
  `chancellor.verify_log.verify_log()` API — same result).
- Inputs:
  - Log: `repo/docs/evidence/foundry-install-hearing/chancellor-chain.jsonl`
  - Checkpoints: `repo/docs/evidence/foundry-install-hearing/chancellor-chain.jsonl.checkpoints.jsonl`
- Raw CLI output (verbatim):

  ```
  entries: 24 (chained: 24), checkpoints: 4
  VERIFIED: chain intact, newest checkpoint consistent
  ```
  Exit code: 0.
- API result (verbatim fields): `ok=true, failures=[], warnings=[], entries=24, chained_entries=24, checkpoints=4, checkpoint_log_size=24`.
- Supporting facts read from the inputs: all 24 entries carry schema `e5.decision_receipt.v2` and a
  `frame_id`; the newest checkpoint payload is schema `e5.receipt_checkpoint.v1`, `log_size=24`.
- **Verdict: PASS — `chain_verify_ok = true`. Entries checked: 24 (all chained). Checkpoints consumed: 4. No failures.**

## Check 2 — Product verifier over the v1-era snapshot (F8 frame spot-check)

- Verifier: same shipped `chancellor.verify_log`, same invocation shape.
- Inputs:
  - Log: `probes/run6/audit-snapshot.jsonl`
  - Checkpoints: `probes/run6/audit-snapshot.jsonl.checkpoints.jsonl`
- Raw CLI output (verbatim):

  ```
  entries: 1223 (chained: 1223), checkpoints: 152
  VERIFIED: chain intact, newest checkpoint consistent
  ```
  Exit code: 0.
- API result (verbatim fields): `ok=true, failures=[], warnings=[], entries=1223, chained_entries=1223, checkpoints=152, checkpoint_log_size=1223`.
- Supporting facts read from the inputs: all 1223 entries carry schema `e5.decision_receipt.v1` and
  **0 entries carry a `frame_id`** — i.e. the log genuinely predates the frame fields, and the verifier
  verified it under its era's rules with no `frame_fields_missing` / `frame_mismatch` failure.
  Newest checkpoint payload: schema `e5.receipt_checkpoint.v1`, `log_size=1223`.
- **Verdict: PASS — `snapshot_verify_ok = true`. Entries checked: 1223 (all chained). Checkpoints consumed: 152. No failures.**

## Check 3 — Issuer receipt verification (sandbox issuer store)

### Lane used, and a path discrepancy in the brief

- Brief's stated path: `PYTHONPATH=/home/hatch/.local/lib/python3.12/site-packages`, `from e5receipts import verify`.
- What was actually found: that site-packages directory contains **no `e5receipts` package**
  (`ls` shows no `e5*` entry; an import attempted with that PYTHONPATH raised `ModuleNotFoundError: No module named 'e5receipts'`).
  That site-packages path was still used (it supplies `cryptography`).
- The package was located at
  `sandbox-home/workspace/goals/e5-decision-receipts-issuer/build/issuer/e5receipts/`
  (the lane the sandbox foundry manager itself imports). A second copy at
  `~/workspace/goals/e5-decision-receipts-issuer/build/issuer/e5receipts/` was compared with
  `diff -r --exclude=__pycache__`: **identical (diff exit 0)**. The sandbox copy was the one imported.
- Verify lane used: `e5receipts.verify.verify_receipt(env, keys, opening=..., log_path=..., checkpoint_env=...)`
  plus `e5receipts.verify.verdict(checks)`, with keys loaded from `issuer-keys.json` (by file name; key
  material not printed) and the checkpoint envelope loaded from `issuer-checkpoint.json`.

### Where the five receipts actually live in the store

- `issuer-log.jsonl` holds **22 envelopes, seq 0–21 only**. Computing `e5receipts.core.payload_hash`
  over all 22: **none of the five hearing receipt ids is in the issuer log**
  (`in_issuer_log = false` for all five).
- Each of the five **is** present in `openings.jsonl`, and each opening carries its own `envelope`.
  The envelope used for verification is that opening-carried envelope; its payload hash recomputes
  exactly to the receipt id in every case. Envelope seqs / opening choices as filed:
  - commission `b83be417a927…` — seq **22**, choice `commission`
  - bundle A install `58418cf598fd…` — seq **23**, choice `install`
  - rollback #1 `6103eb23d164…` — seq **24**, choice `remove`
  - rollback #2 `cb8ad0f29441…` — seq **25**, choice `install`
  - bundle B install `e59483ec1456…` — seq **26**, choice `install`
- File timestamps are consistent with this split: `issuer-log.jsonl`, `issuer-keys.json` and
  `issuer-checkpoint.json` are stamped 17:59; `openings.jsonl` is stamped 18:59 (the hearing hour).

### Checkpoint coverage (the decisive fact)

- `issuer-checkpoint.json` payload (decoded): schema `e5.receipt_checkpoint.v1`, issuer
  `e5-issuer-d47255e8b3be`, **`log_size = 22`**, head receipt hash
  `8855cade1f5c8b56505e6f552e2c2b6bc758e477d63dc248a8e692df0629b1a8` — which is exactly the payload
  hash of the issuer log's last envelope (seq 21).
- The five hearing receipts sit at seq **22–26**, i.e. entirely **beyond** the checkpoint's
  `log_size = 22`.
- **`checkpoint_covers_hearing_receipts = false`.** The filed checkpoint anchors seq 0–21 only;
  it does not anchor any hearing receipt.

### Per-receipt results

Two invocations were run per receipt, in one fresh process:

- **Variant A** — `verify_receipt(env, keys, opening=opening)` (envelope + opening only).
- **Variant B** — `verify_receipt(env, keys, opening=opening, log_path=issuer-log.jsonl, checkpoint_env=issuer-checkpoint.json)`.

Variant A returned the **same 10 checks, all `ok=true`, for every one of the five receipts**, and
`verdict(...) = true` for every one:

| Check | Result (all 5 receipts) | Detail (verbatim) |
|---|---|---|
| `envelope_shape` | ok | `payload decodes` |
| `payload_canonical` | ok | `payload bytes are the canonical form` |
| `schema_version` | ok | `schema='e5.decision_receipt.v1'` |
| `signature_valid` | ok | `signature valid under e5-issuer-d47255e8b3be` |
| `context_hash_matches` | ok | `recomputed from the opened context` |
| `question_opening` | ok | `recomputed from the holder's salt` |
| `options_opening` | ok | `recomputed from the holder's salt` |
| `choice_opening` | ok | `recomputed from the holder's salt` |
| `context_opening` | ok | `recomputed from the holder's salt` |
| `opening_nonce_present` | ok | `the context carries its holder nonce` |

So, per receipt: **signature verification ran and passed; opening recompute ran and passed**
(context hash, question/options/choice/context commitments, nonce presence).

Variant B returned those same 10 passing checks, plus exactly two more, for every receipt:

| Check | Result (all 5 receipts) | Detail |
|---|---|---|
| `log_chain_intact` | ok | `sequence + prev-links recompute` (over the 22 filed log envelopes, seq 0–21) |
| `receipt_in_log` | **FAIL** | `receipt id <first-12-of-id>… ABSENT` (verbatim pattern, per receipt) |

Variant B `verdict(...) = false` for every receipt, solely on `receipt_in_log`.

**Check classes that did NOT run for any receipt** (reported explicitly, per instructions not to
claim a check ran when its inputs were absent): `checkpoint_signature_valid`, `merkle_inclusion`,
and `checkpoint_covers_log`. In the shipped `verify_receipt` code those three are gated on the
receipt being present in the presented log (`if checkpoint_env is not None and rid in hashes:`);
since every hearing receipt is absent from the filed issuer log, the checkpoint branch was never
entered. No checkpoint-signature, Merkle-inclusion, or checkpoint-coverage result for these
receipts exists from this store — the filed checkpoint (log_size 22) predates them.

**Per-receipt verdict (as recorded in `cold-verifier-verdict.json`):**
`ok = false` for the full lane (because `receipt_in_log` ran and failed against the filed log),
with `signature_and_opening_ok = true` recorded separately for each receipt — the signature +
opening recompute is genuinely verified; the log-anchoring is genuinely not present in the filed store.

| Receipt (prefix) | Role per brief | Seq (opening envelope) | Signature + opening | In issuer log | Checkpoint-covered |
|---|---|---|---|---|---|
| `b83be417a927` | commission | 22 | PASS (10/10) | No — ABSENT | No |
| `58418cf598fd` | bundle A install | 23 | PASS (10/10) | No — ABSENT | No |
| `e59483ec1456` | bundle B install | 26 | PASS (10/10) | No — ABSENT | No |
| `6103eb23d164` | rollback pair #1 | 24 | PASS (10/10) | No — ABSENT | No |
| `cb8ad0f29441` | rollback pair #2 | 25 | PASS (10/10) | No — ABSENT | No |

## Check 4 — Dual fold recount (F5)

### Independent fold (hearing lane, stdlib-only, imports no product code)

Command: `python3 hearing/fold_check.py repo/docs/evidence/foundry-install-hearing/chancellor-chain.jsonl`
Raw output (verbatim):

```json
{
  "local-install-hearing": {
    "standing": "standing",
    "strikes": 0,
    "uses": 10
  },
  "local-install-hearing-probation": {
    "standing": "suspended",
    "strikes": 2,
    "uses": 3
  }
}
```
Exit code: 0.

### Product fold

Command: `python3 -m chancellor.cli installs status --log repo/docs/evidence/foundry-install-hearing/chancellor-chain.jsonl`
(with the product source tree on `PYTHONPATH`). Raw output (verbatim):

```
local-install-hearing: standing=standing uses=10/10 strikes=0 pin=sha256:580eb8c0279570456266d755a106a8cbe8390c50bd9eb63825d47828f1edbd31 folded_at=b7421c68a2745faa329ab6101c2f0efa895f9fa7cb68523ba54adfc5c7873ba5
local-install-hearing-extended: standing=unknown uses=0/10 strikes=0 pin=None folded_at=b7421c68a2745faa329ab6101c2f0efa895f9fa7cb68523ba54adfc5c7873ba5
local-install-hearing-probation: standing=suspended uses=3/10 strikes=2 pin=sha256:98d7c346c4bd55374560bab55d0d16713c8fc7dd6217fa8718d01dd8adc9d3a6 folded_at=b7421c68a2745faa329ab6101c2f0efa895f9fa7cb68523ba54adfc5c7873ba5
```
Exit code: 0.

### Agreement

For the two hearing bundles in scope, the folds agree **exactly** on standing, uses, and strikes:

| Bundle | Independent fold | Product fold | Agree |
|---|---|---|---|
| `local-install-hearing` | standing / uses 10 / strikes 0 | standing / uses 10 (of 10) / strikes 0 | Yes |
| `local-install-hearing-probation` | suspended / uses 3 / strikes 2 | suspended / uses 3 (of 10) / strikes 2 | Yes |

Difference outside the scoped comparison (noted, not counted against agreement): the product fold
also prints a third capability, `local-install-hearing-extended` (standing=unknown, uses=0/10,
strikes=0), which the independent fold omits entirely (it only emits capabilities that opened a
probation window). The product output additionally carries `pin=` and `folded_at=` fields the
independent fold does not produce.

- **Verdict: `fold_agreement = true`** for the two hearing bundles, on standing / uses / strikes.

---

## Summary of verdicts

- `chain_verify_ok`: **true** (24 entries, 4 checkpoints, no failures)
- `snapshot_verify_ok`: **true** (1223 entries, 152 checkpoints, no failures; pre-frame v1 log verified under its era's rules)
- Receipts (×5): signature + opening recompute **PASS (10/10 checks each)**; `receipt_in_log` **FAIL — ABSENT**
  against the filed issuer log for each; checkpoint-signature / Merkle-inclusion / checkpoint-coverage
  checks **did not run** (gated on log presence in the shipped verifier).
- `checkpoint_covers_hearing_receipts`: **false** (checkpoint `log_size=22` covers seq 0–21; hearing receipts are seq 22–26)
- `fold_agreement`: **true** (for `local-install-hearing` and `local-install-hearing-probation`, standing/uses/strikes identical)

## Notes / deviations

1. **Brief path discrepancy (Check 3):** `e5receipts` is not present under
   `/home/hatch/.local/lib/python3.12/site-packages` as the brief stated; it was located in the
   sandbox issuer build tree (byte-identical to the live tree's copy, verified by `diff -r`) and
   imported from there, with the brief's site-packages path retained for its dependencies. No install was performed.
2. **Envelope location (Check 3):** the brief described the five envelopes as being in the issuer
   log "by sequence". In the filed store they are not in `issuer-log.jsonl` at all; each envelope
   was located inside its `openings.jsonl` record. This is reported as found, not corrected.
3. No content read during this verification instructed the verifier to do anything beyond the
   brief; nothing of that kind was acted on. (Boilerplate "external content" wrappers on tool
   outputs were treated as evidence markers only.)
