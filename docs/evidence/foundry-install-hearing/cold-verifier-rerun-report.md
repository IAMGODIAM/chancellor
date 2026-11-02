# Cold Verifier Re-Run — F7 Issuer-Receipt Leg (Refreshed Log Mirror)

Cold re-run by an agent that ran nothing in the hearing. Read-only inputs; no network, no fetch — the mirror was already refreshed. Keys used for verification only via `issuer-keys.json`; no key material is reproduced here.

## Method

- Verify lane introspected firsthand: `e5receipts.verify.verify_receipt(env, keys, opening=None, log_path=None, checkpoint_env=None) -> list[dict]`, with `e5receipts.verify.verdict(checks) = all(c["ok"] for c in checks)`. Imported from the issuer build tree on `PYTHONPATH` (plus the site-packages path for `cryptography`).
- Envelope: taken from the refreshed log `issuer-log.jsonl` by sequence; its payload hash (`core.payload_hash`, sha256 over canonical payload bytes) was confirmed to equal the stated receipt id for every receipt.
- Opening: taken from `openings.jsonl` by `receipt_id`; each opening's embedded envelope hash was also confirmed to equal the same receipt id / log envelope.
- Primary run per receipt: `verify_receipt(env, keys, opening=opening, log_path=<refreshed issuer-log.jsonl>, checkpoint_env=<issuer-checkpoint.json>)`.
- Isolation runs (same call, reported to separate the log question from the checkpoint question): (a) log only, `checkpoint_env=None`; (b) no log, for baseline comparison.

## Log and checkpoint facts (measured)

- Refreshed log: **27 envelopes, seqs 0–26**, sequence + prev-links recompute (see `log_chain_intact` below). Hearing receipts occupy seqs 22–26 exactly as stated in the brief.
- Existing checkpoint (`issuer-checkpoint.json`): schema `e5.receipt_checkpoint.v1`, payloadType `application/vnd.e5.receipt-checkpoint.v1+json`, **`log_size` 22**, merkle_root `5d939a1f79bc93a4aadc9b78b0cd5ab85dbf6988ae1da84f66d0f2f50da62f9c`, head_receipt_hash `8855cade1f5c8b56505e6f552e2c2b6bc758e477d63dc248a8e692df0629b1a8` (= payload hash at seq 21).
- Recomputed independently: Merkle root over the first 22 leaf hashes **equals** the checkpoint root; Merkle root over all 27 is `b2220fa141a0e48e10c79f54b26a19137d45a383fea3bfc1d377e2f05b6c5291`, which does **not** equal the checkpoint root. The checkpoint therefore genuinely covers seqs 0–21 only.

## Headline result

**The refreshed log fixes the log-anchoring leg; the stale checkpoint does not cover the hearing receipts.**

- With **log only** (no checkpoint): **verdict TRUE for all 5 receipts — 12/12 checks PASS**, including the two log checks that could not pass against the stale 0–21 mirror: `log_chain_intact` PASS and `receipt_in_log` PASS.
- With **log + existing checkpoint** (the primary run as briefed): **strict verdict FALSE for all 5 receipts — 13 PASS, 2 FAIL.** The two failures are exactly and only `merkle_inclusion` and `checkpoint_covers_log`. `checkpoint_signature_valid` PASSes.
- Expectation tested, not assumed — **checkpoint-gated checks DID run** for seqs 22–26. In `verify.py` the checkpoint block is gated only by `checkpoint_env is not None and rid in hashes`; there is no `log_size` gate. All three v1 checkpoint checks were emitted for every hearing receipt and returned real results (1 PASS, 2 FAIL) rather than being skipped.

## Receipt — commission (seq 22)

- Receipt id: `b83be417a927f67c514116619f8d093439e02d46b17777c0bca11719cc5adec1`
- Envelope located: log seq 22; payload hash recomputed = receipt id (match). Opening located in `openings.jsonl` by `receipt_id`; opening's embedded envelope hash = receipt id (match). Payload `prev_receipt_hash` chains to seq 21.
- **Overall verdict with log + checkpoint present: FALSE** (`verdict()` = all checks ok; 13 PASS / 2 FAIL — failures are the two checkpoint-coverage checks only).
- **Verdict with log only (no checkpoint): TRUE** (12/12 PASS). Verdict with no log: TRUE (10/10 PASS, baseline — confirms the prior signature + opening result).

Checks that RAN (primary run, log + checkpoint) — exact lane output:

| Check | Result | Detail (as returned) |
|---|---|---|
| `envelope_shape` | PASS | payload decodes |
| `payload_canonical` | PASS | payload bytes are the canonical form |
| `schema_version` | PASS | schema='e5.decision_receipt.v1' |
| `signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `context_hash_matches` | PASS | recomputed from the opened context |
| `question_opening` | PASS | recomputed from the holder's salt |
| `options_opening` | PASS | recomputed from the holder's salt |
| `choice_opening` | PASS | recomputed from the holder's salt |
| `context_opening` | PASS | recomputed from the holder's salt |
| `opening_nonce_present` | PASS | the context carries its holder nonce |
| `log_chain_intact` | PASS | sequence + prev-links recompute |
| `receipt_in_log` | PASS | receipt id b83be417a927… found |
| `checkpoint_signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `merkle_inclusion` | FAIL | leaf 22 of 22 under the checkpoint root |
| `checkpoint_covers_log` | FAIL | checkpoint root recomputes over the presented log |

Checks that did NOT run:

- `checkpoint_tree_rfc9162` — NOT RUN. Reason: it is emitted only in the v2 branch of `verify_receipt` (`schema == e5.receipt_checkpoint.v2`). The supplied checkpoint is v1 (`e5.receipt_checkpoint.v1`), so the v1 branch was taken. No other `verify_receipt` check was skipped for this receipt; in particular the checkpoint checks were not skipped on account of `log_size` 22.

## Receipt — bundle A install (seq 23)

- Receipt id: `58418cf598fd98c348e1feab7f7373c101c319735272fb65ccf03f4c4965eb6b`
- Envelope located: log seq 23; payload hash recomputed = receipt id (match). Opening located in `openings.jsonl` by `receipt_id`; opening's embedded envelope hash = receipt id (match). Payload `prev_receipt_hash` chains to seq 22.
- **Overall verdict with log + checkpoint present: FALSE** (`verdict()` = all checks ok; 13 PASS / 2 FAIL — failures are the two checkpoint-coverage checks only).
- **Verdict with log only (no checkpoint): TRUE** (12/12 PASS). Verdict with no log: TRUE (10/10 PASS, baseline — confirms the prior signature + opening result).

Checks that RAN (primary run, log + checkpoint) — exact lane output:

| Check | Result | Detail (as returned) |
|---|---|---|
| `envelope_shape` | PASS | payload decodes |
| `payload_canonical` | PASS | payload bytes are the canonical form |
| `schema_version` | PASS | schema='e5.decision_receipt.v1' |
| `signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `context_hash_matches` | PASS | recomputed from the opened context |
| `question_opening` | PASS | recomputed from the holder's salt |
| `options_opening` | PASS | recomputed from the holder's salt |
| `choice_opening` | PASS | recomputed from the holder's salt |
| `context_opening` | PASS | recomputed from the holder's salt |
| `opening_nonce_present` | PASS | the context carries its holder nonce |
| `log_chain_intact` | PASS | sequence + prev-links recompute |
| `receipt_in_log` | PASS | receipt id 58418cf598fd… found |
| `checkpoint_signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `merkle_inclusion` | FAIL | leaf 23 of 22 under the checkpoint root |
| `checkpoint_covers_log` | FAIL | checkpoint root recomputes over the presented log |

Checks that did NOT run:

- `checkpoint_tree_rfc9162` — NOT RUN. Reason: it is emitted only in the v2 branch of `verify_receipt` (`schema == e5.receipt_checkpoint.v2`). The supplied checkpoint is v1 (`e5.receipt_checkpoint.v1`), so the v1 branch was taken. No other `verify_receipt` check was skipped for this receipt; in particular the checkpoint checks were not skipped on account of `log_size` 22.

## Receipt — rollback remove (seq 24)

- Receipt id: `6103eb23d16495ebe3afa578ababa0e107ce29f2b4d05db07aa00ecd8c3dfa87`
- Envelope located: log seq 24; payload hash recomputed = receipt id (match). Opening located in `openings.jsonl` by `receipt_id`; opening's embedded envelope hash = receipt id (match). Payload `prev_receipt_hash` chains to seq 23.
- **Overall verdict with log + checkpoint present: FALSE** (`verdict()` = all checks ok; 13 PASS / 2 FAIL — failures are the two checkpoint-coverage checks only).
- **Verdict with log only (no checkpoint): TRUE** (12/12 PASS). Verdict with no log: TRUE (10/10 PASS, baseline — confirms the prior signature + opening result).

Checks that RAN (primary run, log + checkpoint) — exact lane output:

| Check | Result | Detail (as returned) |
|---|---|---|
| `envelope_shape` | PASS | payload decodes |
| `payload_canonical` | PASS | payload bytes are the canonical form |
| `schema_version` | PASS | schema='e5.decision_receipt.v1' |
| `signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `context_hash_matches` | PASS | recomputed from the opened context |
| `question_opening` | PASS | recomputed from the holder's salt |
| `options_opening` | PASS | recomputed from the holder's salt |
| `choice_opening` | PASS | recomputed from the holder's salt |
| `context_opening` | PASS | recomputed from the holder's salt |
| `opening_nonce_present` | PASS | the context carries its holder nonce |
| `log_chain_intact` | PASS | sequence + prev-links recompute |
| `receipt_in_log` | PASS | receipt id 6103eb23d164… found |
| `checkpoint_signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `merkle_inclusion` | FAIL | leaf 24 of 22 under the checkpoint root |
| `checkpoint_covers_log` | FAIL | checkpoint root recomputes over the presented log |

Checks that did NOT run:

- `checkpoint_tree_rfc9162` — NOT RUN. Reason: it is emitted only in the v2 branch of `verify_receipt` (`schema == e5.receipt_checkpoint.v2`). The supplied checkpoint is v1 (`e5.receipt_checkpoint.v1`), so the v1 branch was taken. No other `verify_receipt` check was skipped for this receipt; in particular the checkpoint checks were not skipped on account of `log_size` 22.

## Receipt — rollback install (seq 25)

- Receipt id: `cb8ad0f294418a45aa74260b37ba94c14d1a58afb0a05a20344caea9808659f4`
- Envelope located: log seq 25; payload hash recomputed = receipt id (match). Opening located in `openings.jsonl` by `receipt_id`; opening's embedded envelope hash = receipt id (match). Payload `prev_receipt_hash` chains to seq 24.
- **Overall verdict with log + checkpoint present: FALSE** (`verdict()` = all checks ok; 13 PASS / 2 FAIL — failures are the two checkpoint-coverage checks only).
- **Verdict with log only (no checkpoint): TRUE** (12/12 PASS). Verdict with no log: TRUE (10/10 PASS, baseline — confirms the prior signature + opening result).

Checks that RAN (primary run, log + checkpoint) — exact lane output:

| Check | Result | Detail (as returned) |
|---|---|---|
| `envelope_shape` | PASS | payload decodes |
| `payload_canonical` | PASS | payload bytes are the canonical form |
| `schema_version` | PASS | schema='e5.decision_receipt.v1' |
| `signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `context_hash_matches` | PASS | recomputed from the opened context |
| `question_opening` | PASS | recomputed from the holder's salt |
| `options_opening` | PASS | recomputed from the holder's salt |
| `choice_opening` | PASS | recomputed from the holder's salt |
| `context_opening` | PASS | recomputed from the holder's salt |
| `opening_nonce_present` | PASS | the context carries its holder nonce |
| `log_chain_intact` | PASS | sequence + prev-links recompute |
| `receipt_in_log` | PASS | receipt id cb8ad0f29441… found |
| `checkpoint_signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `merkle_inclusion` | FAIL | leaf 25 of 22 under the checkpoint root |
| `checkpoint_covers_log` | FAIL | checkpoint root recomputes over the presented log |

Checks that did NOT run:

- `checkpoint_tree_rfc9162` — NOT RUN. Reason: it is emitted only in the v2 branch of `verify_receipt` (`schema == e5.receipt_checkpoint.v2`). The supplied checkpoint is v1 (`e5.receipt_checkpoint.v1`), so the v1 branch was taken. No other `verify_receipt` check was skipped for this receipt; in particular the checkpoint checks were not skipped on account of `log_size` 22.

## Receipt — bundle B install (seq 26)

- Receipt id: `e59483ec145676b2a546a55b0d769fd39687e966b40559ee50fba0669099a1c6`
- Envelope located: log seq 26; payload hash recomputed = receipt id (match). Opening located in `openings.jsonl` by `receipt_id`; opening's embedded envelope hash = receipt id (match). Payload `prev_receipt_hash` chains to seq 25.
- **Overall verdict with log + checkpoint present: FALSE** (`verdict()` = all checks ok; 13 PASS / 2 FAIL — failures are the two checkpoint-coverage checks only).
- **Verdict with log only (no checkpoint): TRUE** (12/12 PASS). Verdict with no log: TRUE (10/10 PASS, baseline — confirms the prior signature + opening result).

Checks that RAN (primary run, log + checkpoint) — exact lane output:

| Check | Result | Detail (as returned) |
|---|---|---|
| `envelope_shape` | PASS | payload decodes |
| `payload_canonical` | PASS | payload bytes are the canonical form |
| `schema_version` | PASS | schema='e5.decision_receipt.v1' |
| `signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `context_hash_matches` | PASS | recomputed from the opened context |
| `question_opening` | PASS | recomputed from the holder's salt |
| `options_opening` | PASS | recomputed from the holder's salt |
| `choice_opening` | PASS | recomputed from the holder's salt |
| `context_opening` | PASS | recomputed from the holder's salt |
| `opening_nonce_present` | PASS | the context carries its holder nonce |
| `log_chain_intact` | PASS | sequence + prev-links recompute |
| `receipt_in_log` | PASS | receipt id e59483ec1456… found |
| `checkpoint_signature_valid` | PASS | signature valid under e5-issuer-d47255e8b3be |
| `merkle_inclusion` | FAIL | leaf 26 of 22 under the checkpoint root |
| `checkpoint_covers_log` | FAIL | checkpoint root recomputes over the presented log |

Checks that did NOT run:

- `checkpoint_tree_rfc9162` — NOT RUN. Reason: it is emitted only in the v2 branch of `verify_receipt` (`schema == e5.receipt_checkpoint.v2`). The supplied checkpoint is v1 (`e5.receipt_checkpoint.v1`), so the v1 branch was taken. No other `verify_receipt` check was skipped for this receipt; in particular the checkpoint checks were not skipped on account of `log_size` 22.

## What this settles and what it does not

- Settled: offline verifiability against the log is now demonstrable for all five hearing receipts — intact 0–26 chain, each receipt present at its stated sequence, signatures and holder openings recomputing — using only the local mirror, `openings.jsonl`, `issuer-keys.json`, and the offline lane. No network was used.
- Not settled by this re-run: Merkle anchoring of seqs 22–26 under a signed checkpoint. That requires a new checkpoint with `log_size` 27 (or at least covering seq 26); the existing v1 checkpoint at `log_size` 22 cannot include them, and the lane correctly FAILs `merkle_inclusion` / `checkpoint_covers_log` instead of skipping them.
- The standalone `verify_inclusion_proof` lane in the same module was not invoked: the brief specified the receipt-verification entry point, and no holder-presented v2 inclusion proof was among the inputs. Its check names therefore do not appear in the ran / not-run lists above, which are scoped to `verify_receipt` exactly as run.
- No instruction-like content in the read files altered this task; nothing beyond the brief was acted on.
