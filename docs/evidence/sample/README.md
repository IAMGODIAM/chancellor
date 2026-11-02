# Sample evidence — one exhibit run's receipt book

This folder holds the complete audit trail of a single fresh run of the
exhibit (`chancellor demo --fast --auto`, run 2026-11-01 against this
tree): five hash-chained entries and the one signed checkpoint that seals
them. It exists so the receipt claim can be checked without trusting
anything else in this repository — no test suite, no demo, no narration.

| File | What it is |
|---|---|
| `audit-log.jsonl` | The run's append-only audit log: 5 chained entries (the work, the halted fault, the gate's denial and approval, the close). |
| `audit-log.jsonl.checkpoints.jsonl` | The signed checkpoint sidecar: one checkpoint, signed over all 5 entries. The verifier finds it automatically beside the log. |

## Verify it — the zero-install path

You need Python ≥ 3.11 and these two files. Nothing else: no clone, no
credentials, no network beyond the install itself.

```bash
pip install chancellor

# from the folder holding the two files (or point at the path directly):
python -m chancellor.verify_log audit-log.jsonl --accept-dev-signer
```

Expected output:

```
SIGNER: dev-hmac (public) — tamper-evidence only
entries: 5 (chained: 5), checkpoints: 1
VERIFIED: chain intact, newest checkpoint consistent
```

Exit code 0 means every entry's hash recomputes, every link holds, and
the signed checkpoint is consistent with the log it seals. Change one
character in the log and the same command exits 1 and names the failure
(`entry_hash_mismatch`, `prev_hash_link_broken`, `tail_truncation`, …).
A log with no checkpoint is never reported as verified — tail truncation
is undetectable without one, and the verifier says so rather than
guessing.

Inside a clone of this repository the same check is one line from the
repo root:

```bash
python -m chancellor.verify_log docs/evidence/sample/audit-log.jsonl --accept-dev-signer
```

The `--accept-dev-signer` flag acknowledges that the checkpoint is
signed with the development signer: without it the verifier labels the
signer and exits non-zero.

The checkpoint is signed with the development signer whose key ships in
the source — deliberately public, and labeled in the code where it sits:
the signature proves the chain is internally consistent and unaltered
since signing (tamper-evidence), not who signed it (non-repudiation).
Signer separation is the named hardening step — see
[docs/open-register.md](../../open-register.md).
