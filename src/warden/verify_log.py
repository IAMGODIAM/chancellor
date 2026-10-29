"""Offline verifier for Warden's hash-chained audit log.

    python -m warden.verify_log <audit-log.jsonl> [--checkpoints <file>]
                                [--allow-legacy-prefix] [--allow-uncheckpointed]

Re-walks the log trusting nothing from the runtime: every chained
entry's hash is recomputed, every prev-hash link re-checked, and the
newest signed checkpoint is validated (signature, log_size, Merkle
root, head hash). Tamper classes detected, each with a named failure:

  * mid-log edit        -> entry_hash_mismatch / prev_hash_link_broken
  * reordering          -> seq_mismatch / prev_hash_link_broken
  * tail truncation     -> tail_truncation (checkpoint log_size > entries
                           present) or head_hash_mismatch
  * checkpoint forgery  -> checkpoint_signature_invalid /
                           checkpoint_root_mismatch / checkpoint_schema

Exit codes: 0 = verified, 1 = verification failed (named failures on
stdout), 2 = usage / IO error.

Without any checkpoint, tail truncation is undetectable *by
construction* — the verifier refuses to call such a log verified
unless --allow-uncheckpointed is passed. A pre-chain legacy prefix
(plain JSONL written before the chain existed) is reported as
``unchained_legacy_entries`` unless --allow-legacy-prefix is passed.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import receipts


@dataclass
class VerificationResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    entries: int = 0            # lines in the log
    chained_entries: int = 0    # entries carrying a hash-chain link
    checkpoints: int = 0        # checkpoint envelopes seen
    checkpoint_log_size: int | None = None


def _load_jsonl(path: Path, failures: list[str]) -> list[dict] | None:
    if not path.exists():
        failures.append(f"log_not_found: {path}")
        return None
    rows: list[dict] = []
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            failures.append(f"malformed_line: line {lineno} is not JSON")
            return None
    return rows


def verify_log(log_path: str | Path,
               checkpoint_path: str | Path | None = None,
               signer: receipts.Signer | None = None,
               allow_legacy_prefix: bool = False,
               allow_uncheckpointed: bool = False) -> VerificationResult:
    signer = signer if signer is not None else receipts.default_signer()
    failures: list[str] = []
    warnings: list[str] = []

    rows = _load_jsonl(Path(log_path), failures)
    if rows is None:
        return VerificationResult(ok=False, failures=failures)

    # ---- chain walk (manual, so failures are named per class)
    chained_hashes: list[str] = []
    prev_hash: str | None = None
    prev_entry: dict | None = None
    legacy = 0
    chain_started = False
    for pos, entry in enumerate(rows):
        if "entry_hash" not in entry:
            if chain_started:
                failures.append(
                    f"unchained_entry_after_chain_start: position {pos}")
            else:
                legacy += 1
            prev_entry = entry
            continue
        chain_started = True
        expected_prev = (receipts.legacy_anchor(prev_entry)
                         if not chained_hashes and prev_entry is not None
                         and legacy else prev_hash)
        if entry.get("seq") != pos:
            failures.append(
                f"seq_mismatch: position {pos} carries seq={entry.get('seq')!r}")
        if entry.get("prev_hash") != expected_prev:
            failures.append(f"prev_hash_link_broken: seq {pos}")
        if receipts.entry_hash(entry) != entry["entry_hash"]:
            failures.append(f"entry_hash_mismatch: seq {pos} (entry edited)")
        chained_hashes.append(entry.get("entry_hash"))
        prev_hash = entry.get("entry_hash")
        prev_entry = entry

    if legacy:
        msg = (f"unchained_legacy_entries: {legacy} pre-chain line(s) "
               f"carry no hash link")
        (warnings if allow_legacy_prefix else failures).append(msg)

    # ---- checkpoints
    cp_path = (Path(checkpoint_path) if checkpoint_path is not None
               else receipts.default_checkpoint_path(log_path))
    cp_rows: list[dict] = []
    if cp_path.exists():
        loaded = _load_jsonl(cp_path, failures)
        if loaded is not None:
            cp_rows = loaded

    checkpoint_log_size: int | None = None
    if not cp_rows:
        msg = ("no_checkpoint: no signed checkpoint found — tail "
               "truncation is undetectable for this log")
        (warnings if allow_uncheckpointed else failures).append(msg)
    else:
        newest = cp_rows[-1]
        try:
            payload = receipts.checkpoint_payload(newest)
        except Exception:
            failures.append("checkpoint_malformed: newest checkpoint "
                            "envelope does not decode")
            payload = None
        if payload is not None:
            if payload.get("schema") != receipts.CHECKPOINT_SCHEMA:
                failures.append(
                    f"checkpoint_schema: {payload.get('schema')!r} != "
                    f"{receipts.CHECKPOINT_SCHEMA!r}")
            if newest.get("payloadType") != receipts.CHECKPOINT_PAYLOAD_TYPE:
                failures.append("checkpoint_payload_type: unexpected "
                                "payloadType")
            if not receipts.checkpoint_signature_valid(newest, signer):
                failures.append("checkpoint_signature_invalid: newest "
                                "checkpoint signature does not verify")
            checkpoint_log_size = payload.get("log_size")
            if checkpoint_log_size != len(chained_hashes):
                if (isinstance(checkpoint_log_size, int)
                        and checkpoint_log_size > len(chained_hashes)):
                    failures.append(
                        f"tail_truncation: checkpoint covers "
                        f"{checkpoint_log_size} chained entries, log "
                        f"holds {len(chained_hashes)}")
                else:
                    failures.append(
                        f"checkpoint_size_mismatch: checkpoint log_size="
                        f"{checkpoint_log_size!r}, log holds "
                        f"{len(chained_hashes)} chained entries (log grew "
                        f"past the newest checkpoint — re-checkpoint)")
            if chained_hashes and \
                    payload.get("head_receipt_hash") != chained_hashes[-1]:
                failures.append(
                    "head_hash_mismatch: checkpoint head != last entry "
                    "hash in log")
            if payload.get("merkle_root") != \
                    receipts.merkle_root(chained_hashes):
                failures.append(
                    "checkpoint_root_mismatch: Merkle root over the "
                    "log's entry hashes != checkpoint root")

    return VerificationResult(
        ok=not failures, failures=failures, warnings=warnings,
        entries=len(rows), chained_entries=len(chained_hashes),
        checkpoints=len(cp_rows), checkpoint_log_size=checkpoint_log_size)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="warden-verify-log",
        description="Verify a Warden hash-chained audit log offline.")
    parser.add_argument("log", help="path to the audit log JSONL")
    parser.add_argument("--checkpoints", default=None,
                        help="checkpoint sidecar path (default: "
                             "<log>.checkpoints.jsonl)")
    parser.add_argument("--allow-legacy-prefix", action="store_true",
                        help="tolerate pre-chain unchained lines")
    parser.add_argument("--allow-uncheckpointed", action="store_true",
                        help="accept a log with no checkpoint (tail "
                             "truncation then undetectable)")
    args = parser.parse_args(argv)

    if not Path(args.log).exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 2
    result = verify_log(args.log, checkpoint_path=args.checkpoints,
                        allow_legacy_prefix=args.allow_legacy_prefix,
                        allow_uncheckpointed=args.allow_uncheckpointed)
    print(f"entries: {result.entries} (chained: {result.chained_entries}), "
          f"checkpoints: {result.checkpoints}")
    for warning in result.warnings:
        print(f"WARNING: {warning}")
    if result.ok:
        print("VERIFIED: chain intact, newest checkpoint consistent")
        return 0
    for failure in result.failures:
        print(f"FAIL: {failure}")
    print("NOT VERIFIED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
