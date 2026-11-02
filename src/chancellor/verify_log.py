"""Offline verifier for Chancellor's hash-chained audit log.

    python -m chancellor.verify_log <audit-log.jsonl> [--checkpoints <file>]
                                [--allow-legacy-prefix] [--allow-uncheckpointed]
    python -m chancellor.verify_log resolve <audit-log.jsonl> <manifest_sha256>
                                [--checkpoints <file>]

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
) -> VerificationResult:
    """Verify a receipt chain offline: hashes, signatures, checkpoints,
    and the authority invariants. Failures are named per class; an
    unreadable log is a failed verification, never an exception."""
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
        if entry.get("schema") == receipts.SCHEMA:
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
                        f"past the newest checkpoint — re-checkpoint)"
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
) -> VerificationResult:
    """Verify a HOLDER-PRESENTED v2 inclusion proof against the newest
    checkpoint in a sidecar — standalone: the log itself is neither
    needed nor consulted. The checkpoint's signature binds (root,
    log_size, head); the proof must match the checkpoint's count
    exactly (proof_count_mismatch REFUSES the proof outright — an
    anchor without a count verifies nothing, as a rule), and the path
    must fold to the checkpoint root."""
    signer = signer if signer is not None else receipts.default_signer()
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


# CC 24 (radon) — one branch per gap resolve must fail closed on.
def resolve_manifest(
    log_path: str | Path,
    manifest_sha256: str,
    checkpoint_path: str | Path | None = None,
    signer: receipts.Signer | None = None,
) -> ResolveResult:
    """Resolve a freeze manifest hash to its covering test_run receipts
    and the checkpoint that seals them. Fail-closed: a broken chain, an
    absent manifest, a manifest with no covering test run, ANY test run
    bound to a manifest that appears nowhere in the log, or the absence
    of a sealing checkpoint each fail the resolution by name."""
    signer = signer if signer is not None else receipts.default_signer()
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


# ------------------------------------------------- the install bridge audit
# Frame v2's bridge (SPEC-FOUNDRY-CHANCELLOR §1.5): the Chancellor
# chain and the Foundry's act journal are separate chains; neither
# validates the other. This audit — the ONE check class the install
# build adds to the verifier — checks CORRESPONDENCE only: every
# governed act's citation resolves, every decision pre-dates the act
# it authorized (a late decision is no decision), every Foundry
# refusal record pairs with the Chancellor refusal Decision that
# recorded it, and every probation opening's citations resolve.
# Citations are hashes and ids, never paraphrase.


@dataclass
class BridgeAuditResult:
    ok: bool
    failures: list[str] = field(default_factory=list)
    acts_checked: int = 0
    citations_resolved: int = 0
    refusals_paired: int = 0


def _iso_to_epoch(text: object) -> float | None:
    if not isinstance(text, str):
        return None
    try:
        from datetime import datetime

        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _opening_seq(opening: dict) -> int | None:
    """The issuer log index of a holder opening, decoded from its
    envelope payload with the stdlib only (the payload is the
    issuer's canonical JSON; reading it is not importing it)."""
    import base64

    try:
        payload = json.loads(
            base64.b64decode(opening["envelope"]["payload"]).decode("utf-8")
        )
        seq = payload.get("seq")
        return int(seq) if isinstance(seq, int) else None
    except Exception:
        return None


def audit_install_bridge(
    entries: list[dict],
    act_records: list[dict],
    journals: dict[str, dict],
    *,
    scope_bundle_ids: set[str] | None = None,
    issuer_openings: list[dict] | None = None,
) -> BridgeAuditResult:
    """Correspondence audit over a paired Chancellor chain + Foundry
    act journal. ``journals`` maps act_id → {"preflight": dict|None,
    "chancellor_decision": dict|None}. ``scope_bundle_ids`` restricts
    the audit to the frozen scope enumeration (None = every act
    present). Receipt-kind citations (a commission receipt — the
    Foundry-side standing citation) resolve against
    ``issuer_openings`` when supplied."""
    failures: list[str] = []
    acts_checked = 0
    citations_resolved = 0
    refusals_paired = 0

    by_seq: dict[int, dict] = {}
    for entry in entries:
        if isinstance(entry.get("seq"), int):
            by_seq[entry["seq"]] = entry
    openings_by_id: dict[str, dict] = {}
    for opening in issuer_openings or []:
        rid = opening.get("receipt_id")
        if isinstance(rid, str):
            openings_by_id[rid] = opening

    def in_scope(bundle_id: object) -> bool:
        return scope_bundle_ids is None or bundle_id in scope_bundle_ids

    for record in act_records:
        bundle_id = record.get("bundle_id")
        if not in_scope(bundle_id):
            continue
        if record.get("type") == "refusal":
            # Pairing: a Chancellor refusal Decision whose detail
            # cites this record's hash and whose rationale names the
            # Foundry state verbatim.
            record_hash = record.get("record_hash")
            reason = record.get("reason")
            paired = False
            for entry in entries:
                if entry.get("action_class") != "capability_install":
                    continue
                if entry.get("approved") is not False:
                    continue
                detail = entry.get("detail")
                parsed: dict = {}
                if isinstance(detail, str):
                    try:
                        parsed = json.loads(detail)
                    except json.JSONDecodeError:
                        parsed = {}
                if (
                    parsed.get("foundry_refusal_record_hash") == record_hash
                    and isinstance(reason, str)
                    and reason in str(entry.get("rationale", ""))
                ):
                    paired = True
                    break
            if paired:
                refusals_paired += 1
            else:
                failures.append(
                    f"bridge_refusal_unpaired: refusal record "
                    f"{record_hash} ({reason}) for {bundle_id} has no "
                    "Chancellor refusal Decision"
                )
            continue
        if record.get("type") != "act":
            continue
        acts_checked += 1
        act_id = str(record.get("act_id"))
        journal = journals.get(act_id, {})
        preflight = journal.get("preflight") or {}
        preflight_epoch = _iso_to_epoch(preflight.get("at"))
        citation = journal.get("chancellor_decision")
        if isinstance(citation, dict) and citation.get("kind") == (
            "chancellor-decision"
        ):
            seq = citation.get("seq")
            target = by_seq.get(seq) if isinstance(seq, int) else None
            if target is None or target.get("entry_hash") != citation.get("entry_hash"):
                failures.append(
                    f"bridge_citation_unresolved: act {act_id} cites "
                    f"Chancellor seq {seq}, not found in the chain"
                )
                continue
            if target.get("action_class") != "capability_install":
                failures.append(
                    f"bridge_citation_wrong_class: act {act_id} cites "
                    f"seq {seq} (action_class "
                    f"{target.get('action_class')!r})"
                )
                continue
            detail = target.get("detail")
            parsed = {}
            if isinstance(detail, str):
                try:
                    parsed = json.loads(detail)
                except json.JSONDecodeError:
                    parsed = {}
            if parsed.get("bundle_id") != bundle_id or parsed.get("verb") != record.get(
                "verb"
            ):
                failures.append(
                    f"bridge_citation_mismatch: act {act_id} vs the "
                    f"decision at seq {seq} (bundle/verb disagree)"
                )
                continue
            if target.get("approved") is not True:
                failures.append(
                    f"bridge_act_without_approval: act {act_id} cites "
                    f"a decision at seq {seq} that did not approve it"
                )
                continue
            decision_ts = target.get("ts")
            if (
                isinstance(decision_ts, (int, float))
                and preflight_epoch is not None
                and float(decision_ts) > preflight_epoch
            ):
                failures.append(
                    f"bridge_precedence_late: act {act_id}'s decision "
                    f"at seq {seq} post-dates the act's pre-flight — "
                    "a late decision is no decision"
                )
                continue
            citations_resolved += 1
            continue
        # Receipt-kind citation: the act statement's commission block.
        statement: dict = record.get("statement") or {}
        citation_block: dict = statement.get("citation") or {}
        auth: dict = citation_block.get("authorizing_decision") or {}
        receipt_id = auth.get("receipt_id")
        cited_opening = openings_by_id.get(receipt_id) if receipt_id else None
        if cited_opening is None:
            failures.append(
                f"bridge_citation_unresolved: act {act_id} cites "
                f"receipt {receipt_id}, not among the issuer openings"
            )
            continue
        cited_seq = _opening_seq(cited_opening)
        act_seq = record.get("receipt_seq")
        if cited_seq is not None and isinstance(act_seq, int) and cited_seq >= act_seq:
            failures.append(
                f"bridge_precedence_late: act {act_id}'s cited "
                f"decision sits at issuer index {cited_seq}, not "
                f"strictly before the act's own index {act_seq} — "
                "a late decision is no decision"
            )
            continue
        citations_resolved += 1

    # Probation openings: both citations must resolve.
    act_receipt_ids = {
        r.get("receipt_id")
        for r in act_records
        if r.get("type") == "act" and in_scope(r.get("bundle_id"))
    }
    for entry in entries:
        if entry.get("entry_type") != "capability_probation_opened":
            continue
        seq = entry.get("decision_seq")
        target = by_seq.get(seq) if isinstance(seq, int) else None
        if (
            target is None
            or target.get("entry_hash") != entry.get("decision_entry_hash")
            or target.get("action_class") != "capability_install"
            or target.get("approved") is not True
        ):
            failures.append(
                f"bridge_probation_citation_unresolved: probation "
                f"opened at seq {entry.get('seq')} cites decision seq "
                f"{seq}, which does not resolve to its approval"
            )
        if entry.get("install_receipt_id") not in act_receipt_ids and (
            entry.get("install_receipt_id") not in openings_by_id
        ):
            failures.append(
                f"bridge_probation_citation_unresolved: probation "
                f"opened at seq {entry.get('seq')} cites install "
                f"receipt {entry.get('install_receipt_id')}, found in "
                "neither the act journal nor the issuer openings"
            )

    return BridgeAuditResult(
        ok=not failures,
        failures=failures,
        acts_checked=acts_checked,
        citations_resolved=citations_resolved,
        refusals_paired=refusals_paired,
    )


def _load_act_journals(acts_dir: Path) -> tuple[list[dict], dict[str, dict]]:
    records: list[dict] = []
    log_path = acts_dir / "acts.jsonl"
    if log_path.exists():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    journals: dict[str, dict] = {}
    if acts_dir.is_dir():
        for child in sorted(acts_dir.iterdir()):
            if not child.is_dir():
                continue
            journal: dict[str, dict | None] = {
                "preflight": None,
                "chancellor_decision": None,
            }
            for name, key in (
                ("preflight.json", "preflight"),
                ("chancellor-decision.json", "chancellor_decision"),
            ):
                f = child / name
                if f.exists():
                    try:
                        journal[key] = json.loads(f.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        journal[key] = None
            journals[child.name] = journal
    return records, journals


def _bridge_main(argv: list[str]) -> int:
    """Console entry for the bridge verb: audit correspondence
    between a Chancellor chain and a paired Foundry act journal."""
    parser = argparse.ArgumentParser(
        prog="chancellor-verify-log bridge",
        description="Audit citation correspondence between a "
        "Chancellor audit log and a Foundry act journal (frame v2 "
        "bridge — correspondence only; neither chain validates the "
        "other).",
    )
    parser.add_argument("log", help="path to the Chancellor audit log JSONL")
    parser.add_argument(
        "--foundry-acts-dir",
        required=True,
        help="the Foundry acts directory (acts.jsonl + per-act journals)",
    )
    parser.add_argument(
        "--issuer-openings",
        default=None,
        help="holder openings JSONL for receipt-kind citations",
    )
    parser.add_argument(
        "--scope-bundles",
        default=None,
        help="comma-separated bundle ids forming the frozen scope "
        "enumeration (default: every act present)",
    )
    args = parser.parse_args(argv)

    failures: list[str] = []
    entries = _load_jsonl(Path(args.log), failures)
    if entries is None:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1
    records, journals = _load_act_journals(Path(args.foundry_acts_dir))
    openings: list[dict] = []
    if args.issuer_openings:
        openings = [
            json.loads(line)
            for line in Path(args.issuer_openings)
            .read_text(encoding="utf-8")
            .splitlines()
            if line.strip()
        ]
    scope = (
        {b.strip() for b in args.scope_bundles.split(",") if b.strip()}
        if args.scope_bundles
        else None
    )
    result = audit_install_bridge(
        entries,
        records,
        journals,
        scope_bundle_ids=scope,
        issuer_openings=openings,
    )
    print(
        f"acts checked: {result.acts_checked}, citations resolved: "
        f"{result.citations_resolved}, refusals paired: "
        f"{result.refusals_paired}"
    )
    for failure in result.failures:
        print(f"FAIL: {failure}")
    if result.ok:
        print(
            "BRIDGE VERIFIED: every citation resolves, every decision pre-dates its act"
        )
        return 0
    print("BRIDGE NOT VERIFIED")
    return 1


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
    args = parser.parse_args(argv)

    if not Path(args.log).exists():
        print(f"error: log not found: {args.log}", file=sys.stderr)
        return 2
    result = resolve_manifest(args.log, args.manifest, checkpoint_path=args.checkpoints)
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
    if argv and argv[0] == "bridge":
        return _bridge_main(argv[1:])
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
        result = verify_holder_proof(cp_path, proof)
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
    )
    print(
        f"entries: {result.entries} (chained: {result.chained_entries}), "
        f"checkpoints: {result.checkpoints}"
    )
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
