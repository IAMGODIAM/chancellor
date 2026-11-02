"""Offline verifier for Chancellor's hash-chained audit log.

    python -m chancellor.verify_log <audit-log.jsonl> [--checkpoints <file>]
                                [--allow-legacy-prefix] [--allow-uncheckpointed]
                                [--accept-dev-signer]
    python -m chancellor.verify_log resolve <audit-log.jsonl> <manifest_sha256>
                                [--checkpoints <file>] [--accept-dev-signer]

The ``resolve`` verb walks freeze provenance (receipts.freeze_manifest /
test_run entries): given a manifest hash it prints the freeze_manifest
entry, every test_run entry bound to that manifest, and the checkpoint
that seals them — failing closed on any gap (no such manifest, a
manifest with no covering test run, a test run bound to a manifest that
appears nowhere in the log, or no checkpoint sealing the entries).

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
  * frame abuse         -> frame_fields_missing / frame_mismatch
                           (frame-era entries only: an entry declaring
                           the current receipt schema must cite a
                           governing frame this verifier holds, by id
                           and hash, inside its committed body)

Signer label: a log sealed under the built-in dev key
(``chancellor-dev-hmac-sha256``, a public key anyone can recompute) is
tamper-evidence only. The verifier prints ``SIGNER: dev-hmac (public) —
tamper-evidence only`` whenever it sees that key id, and fails such a log
unless ``--accept-dev-signer`` is passed.

Exit codes: 0 = verified, 1 = verification failed (named failures on
stdout), 2 = usage / IO error.

Without any checkpoint, tail truncation is undetectable *by
construction* — the verifier refuses to call such a log verified
unless --allow-uncheckpointed is passed. A pre-chain legacy prefix
(plain JSONL written before the chain existed) is reported as
``unchained_legacy_entries`` unless --allow-legacy-prefix is passed.

Checkpoints may be v1 (``e5.receipt_checkpoint.v1``, duplication tree)
or v2 (``e5.receipt_checkpoint.v2``, RFC 9162 tree); the newest
checkpoint is checked under its own schema's rules (dual-verify).
With ``--proof <file>`` the verifier instead checks a holder-presented
v2 inclusion proof against the newest checkpoint — standalone, the
log is not consulted, and a proof whose tree_size disagrees with the
checkpoint's log_size is refused (``proof_count_mismatch``).
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
    entries: int = 0  # lines in the log
    chained_entries: int = 0  # entries carrying a hash-chain link
    checkpoints: int = 0  # checkpoint envelopes seen
    checkpoint_log_size: int | None = None
    dev_signer: bool = False  # a checkpoint was sealed under the dev key


DEV_SIGNER_LABEL = "SIGNER: dev-hmac (public) — tamper-evidence only"


def _dev_signer_seen(cp_path: Path, signer: receipts.Signer) -> bool:
    """True when the sidecar carries the dev key id (in a signature or as
    a payload issuer), or the verifying signer is the dev signer and a
    checkpoint exists. Reads leniently: a malformed sidecar is the
    verifier's failure to name elsewhere."""
    if not cp_path.exists():
        return False
    seen = False
    for line in cp_path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip():
            continue
        seen = True
        try:
            env = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(env, dict):
            continue
        sigs = env.get("signatures")
        if isinstance(sigs, list) and any(
            isinstance(sg, dict) and sg.get("keyid") == receipts.DEV_SIGNER_KEY_ID
            for sg in sigs
        ):
            return True
        try:
            if receipts.checkpoint_payload(env).get("issuer") == (
                receipts.DEV_SIGNER_KEY_ID
            ):
                return True
        except Exception:
            continue
    return seen and signer.key_id == receipts.DEV_SIGNER_KEY_ID


def _apply_dev_gate(result, cp_path: Path, signer: receipts.Signer, accept: bool):
    """Label a dev-signed result, and fail it unless the caller accepted
    the dev signer."""
    if not _dev_signer_seen(cp_path, signer):
        return result
    result.dev_signer = True
    if accept:
        result.warnings.append(DEV_SIGNER_LABEL)
    else:
        result.failures.append(
            "dev_signer_not_accepted: checkpoints are sealed under the public "
            "dev key — tamper-evidence only; pass --accept-dev-signer to "
            "acknowledge"
        )
        result.ok = False
    return result


def _load_jsonl(path: Path, failures: list[str]) -> list[dict] | None:
    if not path.exists():
        failures.append(f"log_not_found: {path}")
        return None
    rows: list[dict] = []
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            failures.append(f"malformed_line: line {lineno} is not JSON")
            return None
    return rows


# CC 30 (radon) — the verifier's checklist: one branch per failure
# it must name verbatim. Splitting it would scatter the vocabulary.
def verify_log(
    log_path: str | Path,
    checkpoint_path: str | Path | None = None,
    signer: receipts.Signer | None = None,
    allow_legacy_prefix: bool = False,
    allow_uncheckpointed: bool = False,
    accept_dev_signer: bool = False,
) -> VerificationResult:
    """Verify a receipt chain offline (see _verify_log_core). A log sealed
    under the public dev key is labelled and FAILS unless
    ``accept_dev_signer`` is set."""
    signer = signer if signer is not None else receipts.default_signer()
    result = _verify_log_core(
        log_path, checkpoint_path, signer, allow_legacy_prefix, allow_uncheckpointed
    )
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    return _apply_dev_gate(result, cp_path, signer, accept_dev_signer)


def _verify_log_core(
    log_path: str | Path,
    checkpoint_path: str | Path | None,
    signer: receipts.Signer,
    allow_legacy_prefix: bool,
    allow_uncheckpointed: bool,
) -> VerificationResult:
    """Verify a receipt chain offline: hashes, signatures, checkpoints,
    and the authority invariants. Failures are named per class; an
    unreadable log is a failed verification, never an exception."""
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
    frame_era = False
    for pos, entry in enumerate(rows):
        if "entry_hash" not in entry:
            if chain_started:
                failures.append(f"unchained_entry_after_chain_start: position {pos}")
            else:
                legacy += 1
            prev_entry = entry
            continue
        chain_started = True
        expected_prev = (
            receipts.legacy_anchor(prev_entry)
            if not chained_hashes and prev_entry is not None and legacy
            else prev_hash
        )
        if entry.get("seq") != pos:
            failures.append(
                f"seq_mismatch: position {pos} carries seq={entry.get('seq')!r}"
            )
        if entry.get("prev_hash") != expected_prev:
            failures.append(f"prev_hash_link_broken: seq {pos}")
        if receipts.entry_hash(entry) != entry["entry_hash"]:
            failures.append(f"entry_hash_mismatch: seq {pos} (entry edited)")
        schema = entry.get("schema")
        if schema not in (receipts.SCHEMA_V1, receipts.SCHEMA):
            failures.append(
                f"frame_fields_missing: seq {pos} carries schema={schema!r}, "
                f"not a receipt schema this verifier holds (no frame stamp)"
            )
        elif schema == receipts.SCHEMA_V1 and frame_era:
            failures.append(
                f"schema_downgrade: seq {pos} declares {receipts.SCHEMA_V1} "
                f"after the chain entered the frame era"
            )
        if schema == receipts.SCHEMA:
            frame_era = True
            # Frame-era entries (receipt schema v2) must name their
            # governing frame, and the citation must be a frame this
            # verifier holds. Pre-frame (v1) entries skip the check:
            # they verify under the rules of their era.
            if "frame_id" not in entry or "frame_hash" not in entry:
                failures.append(
                    f"frame_fields_missing: seq {pos} declares "
                    f"{receipts.SCHEMA} but carries no frame citation"
                )
            elif not receipts.frame_known(entry["frame_id"], entry["frame_hash"]):
                failures.append(
                    f"frame_mismatch: seq {pos} cites frame "
                    f"{entry['frame_id']!r} with hash "
                    f"{entry['frame_hash']!r} — not a frame this "
                    f"verifier holds"
                )
        chained_hashes.append(entry["entry_hash"])
        prev_hash = entry.get("entry_hash")
        prev_entry = entry

    if legacy:
        msg = f"unchained_legacy_entries: {legacy} pre-chain line(s) carry no hash link"
        (warnings if allow_legacy_prefix else failures).append(msg)

    # ---- checkpoints
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    cp_rows: list[dict] = []
    if cp_path.exists():
        loaded = _load_jsonl(cp_path, failures)
        if loaded is not None:
            cp_rows = loaded

    checkpoint_log_size: int | None = None
    if not cp_rows:
        msg = (
            "no_checkpoint: no signed checkpoint found — tail "
            "truncation is undetectable for this log"
        )
        (warnings if allow_uncheckpointed else failures).append(msg)
    else:
        newest = cp_rows[-1]
        try:
            payload = receipts.checkpoint_payload(newest)
        except Exception:
            failures.append(
                "checkpoint_malformed: newest checkpoint envelope does not decode"
            )
            payload = None
        if payload is not None:
            is_v2 = payload.get("schema") == receipts.CHECKPOINT_SCHEMA_V2
            if payload.get("schema") not in (
                receipts.CHECKPOINT_SCHEMA,
                receipts.CHECKPOINT_SCHEMA_V2,
            ):
                failures.append(
                    f"checkpoint_schema: {payload.get('schema')!r} != "
                    f"{receipts.CHECKPOINT_SCHEMA!r}"
                )
            expected_pt = (
                receipts.CHECKPOINT_PAYLOAD_TYPE_V2
                if is_v2
                else receipts.CHECKPOINT_PAYLOAD_TYPE
            )
            if newest.get("payloadType") != expected_pt:
                failures.append("checkpoint_payload_type: unexpected payloadType")
            if is_v2 and payload.get("tree") != receipts.TREE_RFC9162:
                failures.append(
                    f"checkpoint_tree: v2 checkpoint claims "
                    f"tree={payload.get('tree')!r}, expected "
                    f"{receipts.TREE_RFC9162!r}"
                )
            if not receipts.checkpoint_signature_valid(newest, signer):
                failures.append(
                    "checkpoint_signature_invalid: newest "
                    "checkpoint signature does not verify"
                )
            checkpoint_log_size = payload.get("log_size")
            if checkpoint_log_size != len(chained_hashes):
                if isinstance(checkpoint_log_size, int) and checkpoint_log_size > len(
                    chained_hashes
                ):
                    failures.append(
                        f"tail_truncation: checkpoint covers "
                        f"{checkpoint_log_size} chained entries, log "
                        f"holds {len(chained_hashes)}"
                    )
                else:
                    failures.append(
                        f"checkpoint_size_mismatch: checkpoint log_size="
                        f"{checkpoint_log_size!r}, log holds "
                        f"{len(chained_hashes)} chained entries (log grew "
                        f"past the newest checkpoint — re-checkpoint"
                        + (
                            f"; unsealed tail: "
                            f"{len(chained_hashes) - checkpoint_log_size} entries)"
                            if isinstance(checkpoint_log_size, int)
                            else ")"
                        )
                    )
            if (
                chained_hashes
                and payload.get("head_receipt_hash") != chained_hashes[-1]
            ):
                failures.append(
                    "head_hash_mismatch: checkpoint head != last entry hash in log"
                )
            root_fn = receipts.rfc9162_root if is_v2 else receipts.merkle_root
            if payload.get("merkle_root") != root_fn(chained_hashes):
                failures.append(
                    "checkpoint_root_mismatch: Merkle root over the "
                    "log's entry hashes != checkpoint root"
                )

    return VerificationResult(
        ok=not failures,
        failures=failures,
        warnings=warnings,
        entries=len(rows),
        chained_entries=len(chained_hashes),
        checkpoints=len(cp_rows),
        checkpoint_log_size=checkpoint_log_size,
    )


def verify_holder_proof(
    checkpoint_path: str | Path,
    proof: dict,
    signer: receipts.Signer | None = None,
    accept_dev_signer: bool = False,
) -> VerificationResult:
    """Verify a holder-presented proof (see _verify_holder_proof_core);
    dev-signed checkpoints are labelled and fail unless accepted."""
    signer = signer if signer is not None else receipts.default_signer()
    result = _verify_holder_proof_core(checkpoint_path, proof, signer)
    return _apply_dev_gate(result, Path(checkpoint_path), signer, accept_dev_signer)


def _verify_holder_proof_core(
    checkpoint_path: str | Path,
    proof: dict,
    signer: receipts.Signer,
) -> VerificationResult:
    """Verify a HOLDER-PRESENTED v2 inclusion proof against the newest
    checkpoint in a sidecar — standalone: the log itself is neither
    needed nor consulted. The checkpoint's signature binds (root,
    log_size, head); the proof must match the checkpoint's count
    exactly (proof_count_mismatch REFUSES the proof outright — an
    anchor without a count verifies nothing, as a rule), and the path
    must fold to the checkpoint root."""
    failures: list[str] = []

    cp_rows: list[dict] = []
    loaded = _load_jsonl(Path(checkpoint_path), failures)
    if loaded is not None:
        cp_rows = loaded
    if failures:
        return VerificationResult(ok=False, failures=failures)
    if not cp_rows:
        return VerificationResult(
            ok=False,
            failures=["no_checkpoint: sidecar holds no checkpoint"],
        )
    newest = cp_rows[-1]
    try:
        payload = receipts.checkpoint_payload(newest)
    except Exception:
        return VerificationResult(
            ok=False,
            failures=[
                "checkpoint_malformed: newest checkpoint envelope does not decode"
            ],
            checkpoints=len(cp_rows),
        )
    if payload.get("schema") != receipts.CHECKPOINT_SCHEMA_V2:
        failures.append(
            f"checkpoint_schema: holder proofs require "
            f"{receipts.CHECKPOINT_SCHEMA_V2!r}, newest checkpoint is "
            f"{payload.get('schema')!r}"
        )
    if payload.get("tree") != receipts.TREE_RFC9162:
        failures.append(
            f"checkpoint_tree: tree={payload.get('tree')!r} != "
            f"{receipts.TREE_RFC9162!r}"
        )
    if not receipts.checkpoint_signature_valid(newest, signer):
        failures.append(
            "checkpoint_signature_invalid: newest checkpoint signature does not verify"
        )
    if failures:
        return VerificationResult(
            ok=False,
            failures=failures,
            checkpoints=len(cp_rows),
            checkpoint_log_size=payload.get("log_size"),
        )

    if not isinstance(proof, dict) or not {
        "leaf_hash",
        "index",
        "tree_size",
        "path",
    } <= set(proof):
        failures.append(
            "proof_malformed: proof must carry leaf_hash, index, tree_size, path"
        )
        return VerificationResult(
            ok=False,
            failures=failures,
            checkpoints=len(cp_rows),
            checkpoint_log_size=payload.get("log_size"),
        )
    if proof["tree_size"] != payload.get("log_size"):
        failures.append(
            f"proof_count_mismatch: proof tree_size="
            f"{proof['tree_size']!r} vs checkpoint log_size="
            f"{payload.get('log_size')!r} — refused"
        )
        return VerificationResult(
            ok=False,
            failures=failures,
            checkpoints=len(cp_rows),
            checkpoint_log_size=payload.get("log_size"),
        )
    if not receipts.rfc9162_verify(
        proof["leaf_hash"],
        proof["index"],
        proof["tree_size"],
        proof["path"],
        payload["merkle_root"],
    ):
        failures.append(
            "inclusion_proof_invalid: path does not fold to the checkpoint root"
        )
    return VerificationResult(
        ok=not failures,
        failures=failures,
        checkpoints=len(cp_rows),
        checkpoint_log_size=payload.get("log_size"),
    )


@dataclass
class ResolveResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    manifest_entry: dict | None = None  # the freeze_manifest entry
    test_runs: list[dict] = field(default_factory=list)  # covering test_run entries
    checkpoint: dict | None = None  # payload of the sealing checkpoint
    warnings: list[str] = field(default_factory=list)
    dev_signer: bool = False  # a checkpoint was sealed under the dev key


# CC 24 (radon) — one branch per gap resolve must fail closed on.
def resolve_manifest(
    log_path: str | Path,
    manifest_sha256: str,
    checkpoint_path: str | Path | None = None,
    signer: receipts.Signer | None = None,
    accept_dev_signer: bool = False,
) -> ResolveResult:
    """Resolve a manifest hash (see _resolve_manifest_core); dev-signed
    checkpoints are labelled and fail unless accepted."""
    signer = signer if signer is not None else receipts.default_signer()
    result = _resolve_manifest_core(log_path, manifest_sha256, checkpoint_path, signer)
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    return _apply_dev_gate(result, cp_path, signer, accept_dev_signer)


def _resolve_manifest_core(
    log_path: str | Path,
    manifest_sha256: str,
    checkpoint_path: str | Path | None,
    signer: receipts.Signer,
) -> ResolveResult:
    """Resolve a freeze manifest hash to its covering test_run receipts
    and the checkpoint that seals them. Fail-closed: a broken chain, an
    absent manifest, a manifest with no covering test run, ANY test run
    bound to a manifest that appears nowhere in the log, or the absence
    of a sealing checkpoint each fail the resolution by name."""
    failures: list[str] = []

    rows = _load_jsonl(Path(log_path), failures)
    if rows is None:
        return ResolveResult(ok=False, failures=failures)

    # ---- chain walk (same discipline as verify_log: named failures)
    chained: list[dict] = []
    prev_hash: str | None = None
    prev_entry: dict | None = None
    legacy = 0
    chain_started = False
    for pos, entry in enumerate(rows):
        if "entry_hash" not in entry:
            if chain_started:
                failures.append(f"unchained_entry_after_chain_start: position {pos}")
            else:
                legacy += 1
            prev_entry = entry
            continue
        chain_started = True
        expected_prev = (
            receipts.legacy_anchor(prev_entry)
            if not chained and prev_entry is not None and legacy
            else prev_hash
        )
        if entry.get("seq") != pos:
            failures.append(
                f"seq_mismatch: position {pos} carries seq={entry.get('seq')!r}"
            )
        if entry.get("prev_hash") != expected_prev:
            failures.append(f"prev_hash_link_broken: seq {pos}")
        if receipts.entry_hash(entry) != entry["entry_hash"]:
            failures.append(f"entry_hash_mismatch: seq {pos} (entry edited)")
        chained.append(entry)
        prev_hash = entry.get("entry_hash")
        prev_entry = entry
    if failures:
        return ResolveResult(ok=False, failures=failures)

    chained_pos = {id(e): i for i, e in enumerate(chained)}

    # ---- the manifest and its covering runs
    manifests = {
        e.get("manifest_sha256"): e
        for e in chained
        if e.get("entry_type") == receipts.ENTRY_TYPE_FREEZE_MANIFEST
    }
    manifest_entry = manifests.get(manifest_sha256)
    if manifest_entry is None:
        failures.append(
            f"manifest_not_found: no freeze_manifest entry carries "
            f"manifest_sha256={manifest_sha256}"
        )
        return ResolveResult(ok=False, failures=failures)

    test_runs = [
        e for e in chained if e.get("entry_type") == receipts.ENTRY_TYPE_TEST_RUN
    ]
    for run in test_runs:
        if run.get("manifest_sha256") not in manifests:
            failures.append(
                f"test_run_unknown_manifest: test_run at seq {run.get('seq')} "
                f"binds manifest_sha256={run.get('manifest_sha256')!r}, "
                f"which no freeze_manifest entry in this log carries"
            )
    covering = [r for r in test_runs if r.get("manifest_sha256") == manifest_sha256]
    if not covering:
        failures.append(
            f"manifest_without_test_run: manifest {manifest_sha256} has "
            f"no covering test_run entry"
        )

    # ---- the sealing checkpoint: earliest valid checkpoint whose
    # committed size covers the manifest entry and every covering run.
    needed = (
        max([chained_pos[id(manifest_entry)]] + [chained_pos[id(r)] for r in covering])
        + 1
        if covering
        else chained_pos[id(manifest_entry)] + 1
    )
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    cp_rows: list[dict] = []
    if cp_path.exists():
        loaded = _load_jsonl(cp_path, failures)
        if loaded is not None:
            cp_rows = loaded
    sealing: dict | None = None
    if not cp_rows:
        failures.append(
            "no_checkpoint: no signed checkpoint found — the entries are unsealed"
        )
    else:
        leaves = [e["entry_hash"] for e in chained]
        for envelope in cp_rows:
            try:
                payload = receipts.checkpoint_payload(envelope)
            except Exception:
                failures.append(
                    "checkpoint_malformed: a checkpoint envelope does not decode"
                )
                continue
            if payload.get("schema") != receipts.CHECKPOINT_SCHEMA:
                failures.append(
                    f"checkpoint_schema: {payload.get('schema')!r} != "
                    f"{receipts.CHECKPOINT_SCHEMA!r}"
                )
                continue
            if not receipts.checkpoint_signature_valid(envelope, signer):
                failures.append(
                    "checkpoint_signature_invalid: a checkpoint signature "
                    "does not verify"
                )
                continue
            size = payload.get("log_size")
            if not isinstance(size, int) or size < needed or size > len(leaves):
                continue  # valid, but does not seal these entries (yet)
            if payload.get("merkle_root") != receipts.merkle_root(leaves[:size]):
                failures.append(
                    "checkpoint_root_mismatch: checkpoint root does not "
                    "recompute over the entries it claims to seal"
                )
                continue
            if payload.get("head_receipt_hash") != leaves[size - 1]:
                failures.append(
                    "head_hash_mismatch: checkpoint head != entry hash at "
                    "the seal boundary"
                )
                continue
            sealing = payload
            break
        if sealing is None and not failures:
            failures.append(
                f"checkpoint_not_covering: no checkpoint seals the "
                f"manifest and its covering test runs (needs log_size "
                f">= {needed})"
            )

    return ResolveResult(
        ok=not failures,
        failures=failures,
        manifest_entry=manifest_entry,
        test_runs=covering,
        checkpoint=sealing,
    )


def _resolve_main(argv: list[str]) -> int:
    """Console entry for the resolve verb."""
    parser = argparse.ArgumentParser(
        prog="chancellor-verify-log resolve",
        description="Resolve a freeze manifest hash to its covering "
        "test_run receipts and sealing checkpoint.",
    )
    parser.add_argument("log", help="path to the audit log JSONL")
    parser.add_argument("manifest", help="manifest_sha256 to resolve")
    parser.add_argument(
        "--checkpoints",
        default=None,
        help="checkpoint sidecar path (default: <log>.checkpoints.jsonl)",
    )
    parser.add_argument(
        "--accept-dev-signer",
        action="store_true",
        help="acknowledge checkpoints sealed under the public dev key "
        "(tamper-evidence only); without it such a log fails",
    )
    args = parser.parse_args(argv)

    if not Path(args.log).exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 2
    result = resolve_manifest(
        args.log,
        args.manifest,
        checkpoint_path=args.checkpoints,
        accept_dev_signer=args.accept_dev_signer,
    )
    if result.dev_signer:
        print(DEV_SIGNER_LABEL)
    if result.manifest_entry is not None:
        m = result.manifest_entry
        print(
            f"manifest: seq {m.get('seq')} entry {m.get('entry_hash')} "
            f"({m.get('file_count')} files, suite {m.get('suite_id')!r}, "
            f"head {m.get('head')!r}, recorded_by {m.get('recorded_by')!r})"
        )
    for run in result.test_runs:
        print(
            f"test_run: seq {run.get('seq')} suite {run.get('suite')!r} "
            f"passed={run.get('passed')} failed={run.get('failed')} "
            f"report {run.get('report_sha256')} seat {run.get('seat')!r}"
        )
    if result.checkpoint is not None:
        cp = result.checkpoint
        print(
            f"sealed_by: checkpoint log_size={cp.get('log_size')} "
            f"merkle_root={cp.get('merkle_root')} "
            f"head={cp.get('head_receipt_hash')}"
        )
    for failure in result.failures:
        print(f"FAIL: {failure}")
    if result.ok:
        print("RESOLVED: manifest, covering test runs, and sealing checkpoint")
        return 0
    print("NOT RESOLVED")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Console entry point for the offline verifier (chancellor-verify-log)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "resolve":
        return _resolve_main(argv[1:])
    parser = argparse.ArgumentParser(
        prog="chancellor-verify-log",
        description="Verify a Chancellor hash-chained audit log offline.",
    )
    parser.add_argument("log", help="path to the audit log JSONL")
    parser.add_argument(
        "--checkpoints",
        default=None,
        help="checkpoint sidecar path (default: <log>.checkpoints.jsonl)",
    )
    parser.add_argument(
        "--allow-legacy-prefix",
        action="store_true",
        help="tolerate pre-chain unchained lines",
    )
    parser.add_argument(
        "--allow-uncheckpointed",
        action="store_true",
        help="accept a log with no checkpoint (tail truncation then undetectable)",
    )
    parser.add_argument(
        "--accept-dev-signer",
        action="store_true",
        help="acknowledge checkpoints sealed under the public dev key "
        "(tamper-evidence only); without it such a log fails",
    )
    parser.add_argument(
        "--proof",
        default=None,
        help="verify a holder-presented v2 inclusion proof (JSON file) "
        "against the newest checkpoint in the sidecar — standalone: "
        "the log is not consulted",
    )
    args = parser.parse_args(argv)

    if args.proof is not None:
        cp_path = (
            Path(args.checkpoints)
            if args.checkpoints is not None
            else receipts.default_checkpoint_path(args.log)
        )
        if not cp_path.exists():
            print(f"error: checkpoints not found: {cp_path}", file=sys.stderr)
            return 2
        try:
            proof = json.loads(Path(args.proof).read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"error: proof file unreadable: {exc}", file=sys.stderr)
            return 2
        result = verify_holder_proof(
            cp_path, proof, accept_dev_signer=args.accept_dev_signer
        )
        if result.dev_signer:
            print(DEV_SIGNER_LABEL)
        print(
            f"checkpoints: {result.checkpoints}, "
            f"checkpoint log_size: {result.checkpoint_log_size}"
        )
        if result.ok:
            print("VERIFIED: holder proof folds to the checkpoint root")
            return 0
        for failure in result.failures:
            print(f"FAIL: {failure}")
        print("NOT VERIFIED")
        return 1

    if not Path(args.log).exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 2
    result = verify_log(
        args.log,
        checkpoint_path=args.checkpoints,
        allow_legacy_prefix=args.allow_legacy_prefix,
        allow_uncheckpointed=args.allow_uncheckpointed,
        accept_dev_signer=args.accept_dev_signer,
    )
    if result.dev_signer:
        print(DEV_SIGNER_LABEL)
    print(
        f"entries: {result.entries} (chained: {result.chained_entries}), "
        f"checkpoints: {result.checkpoints}"
    )
    for warning in result.warnings:
        if warning != DEV_SIGNER_LABEL:
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
