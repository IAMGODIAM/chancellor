"""Offline verifier for Chancellor's hash-chained audit log.

    python -m chancellor.verify_log <audit-log.jsonl> --pubkey <key|file>
                                [--checkpoints <file>]
                                [--allow-legacy-prefix] [--allow-uncheckpointed]
    python -m chancellor.verify_log resolve <audit-log.jsonl> <manifest_sha256>
                                --pubkey <key|file> [--checkpoints <file>]

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

Authenticity: a log is VERIFIED only when its checkpoints are signed by
a key the user pinned with ``--pubkey`` (an Ed25519 public key, or the
key id of an operator HMAC key whose secret the verifier holds) and that
key is not the built-in dev key. A log sealed under the public dev key
(``chancellor-dev-hmac-sha256``, which anyone can recompute) prints
``DEV-SIGNED, NOT AUTHENTIC``: its chain can be checked for consistency,
but nobody can show who sealed it. A log with no pinned signer is never
reported as authentic.

Exit codes: 0 = verified AND authentic (pinned, non-dev signer), 1 = not
verified or not authentic (named failures on stdout), 2 = usage / IO error.

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
import base64
import json
import os
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
    # The chain and checkpoints are internally consistent, whatever the
    # signer. Consistency is not authenticity.
    consistent: bool = False
    # Consistent AND sealed under the pinned, non-dev signer. Only this
    # may be reported as VERIFIED.
    authentic: bool = False
    signer_key_id: str | None = None


DEV_SIGNER_LABEL = receipts.DEV_SIGNED_LABEL
DEV_SIGNER_NOTE = (
    "sealed under the public dev key: the chain can be checked for "
    "consistency, but anyone can re-seal it, so it shows nothing about who "
    "wrote it"
)
NOT_AUTHENTIC_LABEL = "NOT AUTHENTIC"


def verdict_of(result: VerificationResult | ResolveResult) -> str:
    """The one-line verdict a CLI or demo may print. VERIFIED/RESOLVED
    wording is reserved for authentic results."""
    if result.authentic:
        return "authentic"
    if result.dev_signer:
        return DEV_SIGNER_LABEL
    if result.ok:
        return NOT_AUTHENTIC_LABEL
    return "not verified"


def _sidecar_has_checkpoint(cp_path: Path) -> bool:
    if not cp_path.exists():
        return False
    return any(
        line.strip()
        for line in cp_path.read_text(encoding="utf-8", errors="replace").splitlines()
    )


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


def _apply_signer_gate(result, cp_path: Path, signer: receipts.Signer, accept: bool):
    """Decide authenticity. The verifying ``signer`` is the pin: a result
    is authentic only when it is consistent, a checkpoint exists, and
    the pinned signer is not the public dev key. A dev-signed result is
    labelled and fails unless the caller acknowledged the non-production
    signer; even then it is never authentic."""
    result.consistent = result.ok
    result.signer_key_id = signer.key_id
    dev = _dev_signer_seen(cp_path, signer)
    result.dev_signer = dev
    if dev:
        if accept:
            result.warnings.append(DEV_SIGNER_LABEL)
        else:
            result.failures.append(
                f"dev_signed_not_authentic: {DEV_SIGNER_LABEL} — {DEV_SIGNER_NOTE}"
            )
            result.ok = False
        return result
    result.authentic = result.ok and _sidecar_has_checkpoint(cp_path)
    return result


def _checkpoint_envelope_keyids(envelope: dict) -> list[str]:
    sigs = envelope.get("signatures") if isinstance(envelope, dict) else None
    if not isinstance(sigs, list):
        return []
    return [str(sg.get("keyid")) for sg in sigs if isinstance(sg, dict)]


def _signature_failures(
    envelope: dict, signer: receipts.Signer, which: str
) -> list[str]:
    """Named failures for one envelope's signature under the pinned
    signer: a key id that is not the pinned one, then the signature
    itself."""
    out: list[str] = []
    ids = _checkpoint_envelope_keyids(envelope)
    if ids != [signer.key_id]:
        out.append(
            f"signer_not_pinned: {which} checkpoint is signed by "
            f"{ids or 'no key'}, not the pinned signer {signer.key_id!r}"
        )
    if not receipts.checkpoint_signature_valid(envelope, signer):
        out.append(
            f"checkpoint_signature_invalid: {which} checkpoint signature "
            "does not verify"
        )
    return out


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
    """Verify a receipt chain offline (see _verify_log_core).

    ``signer`` is the pin: the key the checkpoints must be signed by. A
    result is ``authentic`` only when it is consistent and pinned to a
    non-dev signer. With no ``signer`` the public dev signer is used, so
    a dev-signed log is labelled and FAILS unless ``accept_dev_signer``
    acknowledges the non-production signer — and even then it is never
    authentic."""
    signer = signer if signer is not None else receipts.public_dev_signer()
    result = _verify_log_core(
        log_path, checkpoint_path, signer, allow_legacy_prefix, allow_uncheckpointed
    )
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    return _apply_signer_gate(result, cp_path, signer, accept_dev_signer)


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
            failures.extend(_signature_failures(newest, signer, "newest"))
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

    _check_checkpoint_history(cp_rows, chained_hashes, signer, failures)
    _check_outcomes([r for r in rows if "entry_hash" in r], failures)

    return VerificationResult(
        ok=not failures,
        failures=failures,
        warnings=warnings,
        entries=len(rows),
        chained_entries=len(chained_hashes),
        checkpoints=len(cp_rows),
        checkpoint_log_size=checkpoint_log_size,
    )


def _check_checkpoint_history(
    cp_rows: list[dict],
    chained_hashes: list[str],
    signer: receipts.Signer,
    failures: list[str],
) -> None:
    """Every checkpoint in the sidecar, not only the newest, must agree
    with the log: a signature from the pinned signer, a size that never
    shrinks, a root and head that recompute over the prefix it claims,
    and no v1 checkpoint after a v2 one."""
    seen_v2 = False
    previous_size = 0
    last = len(cp_rows) - 1
    for idx, envelope in enumerate(cp_rows):
        try:
            payload = receipts.checkpoint_payload(envelope)
        except Exception:
            if idx != last:
                failures.append(
                    f"checkpoint_malformed: checkpoint {idx} does not decode"
                )
            continue
        schema = payload.get("schema")
        if schema == receipts.CHECKPOINT_SCHEMA_V2:
            seen_v2 = True
        elif schema == receipts.CHECKPOINT_SCHEMA and seen_v2:
            failures.append(
                f"checkpoint_schema_downgrade: checkpoint {idx} is v1 after "
                "a v2 checkpoint"
            )
        size = payload.get("log_size")
        if isinstance(size, int) and size < previous_size:
            failures.append(
                f"checkpoint_size_regressed: checkpoint {idx} commits {size} "
                f"entries after one that committed {previous_size}"
            )
        if isinstance(size, int):
            previous_size = max(previous_size, size)
        if idx == last:
            continue  # the newest is checked in full by the caller
        if schema not in (receipts.CHECKPOINT_SCHEMA, receipts.CHECKPOINT_SCHEMA_V2):
            failures.append(f"checkpoint_schema: checkpoint {idx} is {schema!r}")
            continue
        failures.extend(_signature_failures(envelope, signer, f"checkpoint {idx}"))
        if not isinstance(size, int) or size < 0 or size > len(chained_hashes):
            failures.append(
                f"checkpoint_history_inconsistent: checkpoint {idx} commits "
                f"{size!r} entries, log holds {len(chained_hashes)}"
            )
            continue
        root_fn = (
            receipts.rfc9162_root
            if schema == receipts.CHECKPOINT_SCHEMA_V2
            else receipts.merkle_root
        )
        head = chained_hashes[size - 1] if size else None
        if payload.get("merkle_root") != root_fn(chained_hashes[:size]) or (
            payload.get("head_receipt_hash") != head
        ):
            failures.append(
                f"checkpoint_history_inconsistent: checkpoint {idx} does not "
                "match the log prefix it seals"
            )


def _check_outcomes(chained: list[dict], failures: list[str]) -> None:
    """Brokered calls leave two records: the decision (carrying a
    ``call_id``) and, after it, the outcome. An approved decision with no
    matching outcome, an outcome with no approved decision, or an outcome
    whose executed arguments differ from the approved ones, fails."""
    decisions: dict[str, tuple[int, dict]] = {}
    outcomes: dict[str, list[tuple[int, dict]]] = {}
    for pos, entry in enumerate(chained):
        call_id = entry.get("call_id")
        if entry.get("entry_type") == receipts.ENTRY_TYPE_TOOL_OUTCOME:
            outcomes.setdefault(str(call_id), []).append((pos, entry))
        elif isinstance(call_id, str) and "approved" in entry:
            decisions[call_id] = (pos, entry)
    for call_id, (pos, decision) in decisions.items():
        found = outcomes.get(call_id, [])
        if not decision.get("approved"):
            if found:
                failures.append(
                    f"outcome_for_denied_call: seq {pos} was denied but call "
                    f"{call_id} has an outcome"
                )
            continue
        if len(found) != 1 or found[0][0] < pos:
            failures.append(
                f"approval_without_outcome: seq {pos} approved call {call_id} "
                f"({decision.get('tool')!r}) with "
                f"{'no' if not found else len(found)} matching outcome"
            )
            continue
        outcome = found[0][1]
        if (
            outcome.get("tool") != decision.get("tool")
            or outcome.get("node_id") != decision.get("node_id")
            or outcome.get("approved_args_sha256") != decision.get("args_sha256")
        ):
            failures.append(
                f"outcome_mismatch: call {call_id} outcome does not match "
                f"the approved decision at seq {pos}"
            )
        elif outcome.get("result_status") in ("ok", "error") and outcome.get(
            "executed_args_sha256"
        ) != outcome.get("approved_args_sha256"):
            failures.append(
                f"outcome_args_mismatch: call {call_id} ran with arguments "
                f"other than the approved ones (seq {pos})"
            )
    for call_id, group in outcomes.items():
        if call_id not in decisions:
            failures.append(
                f"outcome_without_approval: outcome at seq {group[0][0]} "
                f"names call {call_id}, which no decision in this log carries"
            )


def verify_holder_proof(
    checkpoint_path: str | Path,
    proof: dict,
    signer: receipts.Signer | None = None,
    accept_dev_signer: bool = False,
) -> VerificationResult:
    """Verify a holder-presented proof (see _verify_holder_proof_core);
    dev-signed checkpoints are labelled and fail unless accepted."""
    signer = signer if signer is not None else receipts.public_dev_signer()
    result = _verify_holder_proof_core(checkpoint_path, proof, signer)
    return _apply_signer_gate(result, Path(checkpoint_path), signer, accept_dev_signer)


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
    failures.extend(_signature_failures(newest, signer, "newest"))
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
    consistent: bool = False
    authentic: bool = False
    signer_key_id: str | None = None


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
    signer = signer if signer is not None else receipts.public_dev_signer()
    result = _resolve_manifest_core(log_path, manifest_sha256, checkpoint_path, signer)
    cp_path = (
        Path(checkpoint_path)
        if checkpoint_path is not None
        else receipts.default_checkpoint_path(log_path)
    )
    return _apply_signer_gate(result, cp_path, signer, accept_dev_signer)


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
        seen_v2_checkpoint = False
        for envelope in cp_rows:
            try:
                payload = receipts.checkpoint_payload(envelope)
            except Exception:
                failures.append(
                    "checkpoint_malformed: a checkpoint envelope does not decode"
                )
                continue
            schema = payload.get("schema")
            if schema not in (
                receipts.CHECKPOINT_SCHEMA,
                receipts.CHECKPOINT_SCHEMA_V2,
            ):
                failures.append(
                    f"checkpoint_schema: {schema!r} is not "
                    f"{receipts.CHECKPOINT_SCHEMA!r} or "
                    f"{receipts.CHECKPOINT_SCHEMA_V2!r}"
                )
                continue
            if schema == receipts.CHECKPOINT_SCHEMA_V2:
                seen_v2_checkpoint = True
            elif seen_v2_checkpoint:
                failures.append(
                    "checkpoint_schema_downgrade: a v1 checkpoint follows a v2 one"
                )
                continue
            if not receipts.checkpoint_signature_valid(envelope, signer):
                failures.append(
                    "checkpoint_signature_invalid: a checkpoint signature "
                    "does not verify"
                )
                continue
            root_fn = (
                receipts.rfc9162_root
                if schema == receipts.CHECKPOINT_SCHEMA_V2
                else receipts.merkle_root
            )
            size = payload.get("log_size")
            if not isinstance(size, int) or size < needed or size > len(leaves):
                continue  # valid, but does not seal these entries (yet)
            if payload.get("merkle_root") != root_fn(leaves[:size]):
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


PUBKEY_HELP = (
    "pin the signer: an Ed25519 public key ('ed25519:<base64>' or 64 hex "
    "characters, or a file holding one), or an operator HMAC key id "
    "('hmac-sha256:<id>', verified with the secret in "
    f"{receipts.VERIFY_KEY_ENV}). A log is reported authentic only when "
    "its checkpoints are signed by the pinned, non-dev key"
)
ACCEPT_DEV_HELP = (
    "acknowledge a non-production signer: the output stays "
    "'DEV-SIGNED, NOT AUTHENTIC' and the exit status stays non-zero"
)


def load_pinned_signer(spec: str) -> receipts.Signer:
    """Build the verifying signer for a ``--pubkey`` value (a literal or
    the path of a file holding one). Raises ValueError when the value is
    not a usable pin. Nothing here reads a private signing key: an
    Ed25519 pin is public, and an HMAC pin is checked against the secret
    the verifier's operator supplies in the environment."""
    text = spec.strip()
    candidate = Path(text)
    try:
        if candidate.is_file():
            text = candidate.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    if text == receipts.DEV_SIGNER_KEY_ID:
        return receipts.default_signer()
    if text.startswith(receipts.HMAC_KEY_ID_PREFIX):
        secret = os.environ.get(receipts.VERIFY_KEY_ENV)
        if not secret:
            raise ValueError(
                "an HMAC key id needs the verifying secret in "
                f"{receipts.VERIFY_KEY_ENV}"
            )
        signer = receipts.DevHmacSigner(secret=secret.encode("utf-8"))
        if signer.key_id != text:
            raise ValueError(
                f"the secret in {receipts.VERIFY_KEY_ENV} does not match the "
                "pinned key id"
            )
        return signer
    raw = (
        text[len(receipts.ED25519_KEY_ID_PREFIX) :]
        if text.startswith(receipts.ED25519_KEY_ID_PREFIX)
        else text
    )
    key: bytes | None = None
    if len(raw) == 64:
        try:
            key = bytes.fromhex(raw)
        except ValueError:
            key = None
    if key is None:
        try:
            key = base64.b64decode(raw, validate=True)
        except Exception:
            key = None
    if key is None or len(key) != 32:
        raise ValueError(
            "not a usable pin: give an Ed25519 public key (32 bytes, base64 or "
            "hex) or an operator key id; a key id alone cannot check an "
            "Ed25519 signature"
        )
    return receipts.PinnedEd25519Verifier(key)


def _signer_from_args(pubkey: str | None) -> receipts.Signer | None:
    return load_pinned_signer(pubkey) if pubkey is not None else None


def _add_signer_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pubkey", default=None, metavar="KEY_OR_FILE", help=PUBKEY_HELP
    )
    parser.add_argument(
        "--accept-dev-signer", action="store_true", help=ACCEPT_DEV_HELP
    )


def _print_signer_status(result: VerificationResult | ResolveResult) -> None:
    if result.dev_signer:
        print(DEV_SIGNER_LABEL)
        print(f"  {DEV_SIGNER_NOTE}")
    elif result.consistent and not result.authentic:
        print(f"{NOT_AUTHENTIC_LABEL}: no signed checkpoint to pin")
    if result.authentic:
        print(f"signer: {result.signer_key_id} (pinned)")


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
    _add_signer_args(parser)
    args = parser.parse_args(argv)

    if not Path(args.log).exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 2
    try:
        signer = _signer_from_args(args.pubkey)
    except ValueError as exc:
        print(f"error: --pubkey: {exc}", file=sys.stderr)
        return 2
    result = resolve_manifest(
        args.log,
        args.manifest,
        checkpoint_path=args.checkpoints,
        signer=signer,
        accept_dev_signer=args.accept_dev_signer,
    )
    _print_signer_status(result)
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
    if result.authentic:
        print("RESOLVED: manifest, covering test runs, and sealing checkpoint")
        return 0
    print("NOT RESOLVED" if not result.consistent else f"{verdict_of(result)}")
    return 1


def main(argv: list[str] | None = None) -> int:
    """Console entry point for the offline verifier (chancellor-verify-log)."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "resolve":
        return _resolve_main(argv[1:])
    parser = argparse.ArgumentParser(
        prog="chancellor-verify-log",
        description="Verify a Chancellor hash-chained audit log offline. "
        "A log is VERIFIED only when its checkpoints are signed by the "
        "key pinned with --pubkey.",
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
    _add_signer_args(parser)
    parser.add_argument(
        "--proof",
        default=None,
        help="verify a holder-presented v2 inclusion proof (JSON file) "
        "against the newest checkpoint in the sidecar — standalone: "
        "the log is not consulted",
    )
    args = parser.parse_args(argv)
    try:
        signer = _signer_from_args(args.pubkey)
    except ValueError as exc:
        print(f"error: --pubkey: {exc}", file=sys.stderr)
        return 2

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
            cp_path, proof, signer=signer, accept_dev_signer=args.accept_dev_signer
        )
        _print_signer_status(result)
        print(
            f"checkpoints: {result.checkpoints}, "
            f"checkpoint log_size: {result.checkpoint_log_size}"
        )
        if result.authentic:
            print("VERIFIED: holder proof folds to the checkpoint root")
            return 0
        for failure in result.failures:
            print(f"FAIL: {failure}")
        print(verdict_of(result) if result.consistent else "NOT VERIFIED")
        return 1

    if not Path(args.log).exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 2
    result = verify_log(
        args.log,
        checkpoint_path=args.checkpoints,
        signer=signer,
        allow_legacy_prefix=args.allow_legacy_prefix,
        allow_uncheckpointed=args.allow_uncheckpointed,
        accept_dev_signer=args.accept_dev_signer,
    )
    _print_signer_status(result)
    print(
        f"entries: {result.entries} (chained: {result.chained_entries}), "
        f"checkpoints: {result.checkpoints}"
    )
    for warning in result.warnings:
        if warning != DEV_SIGNER_LABEL:
            print(f"WARNING: {warning}")
    if result.authentic:
        print("VERIFIED: chain intact, newest checkpoint consistent")
        return 0
    for failure in result.failures:
        print(f"FAIL: {failure}")
    if result.consistent and signer is None and not result.dev_signer:
        print("NOT AUTHENTIC: no signer pinned (pass --pubkey)")
    print(verdict_of(result) if result.consistent else "NOT VERIFIED")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
