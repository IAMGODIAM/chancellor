"""Hash-chained receipts + signed Merkle checkpoints for the audit log.

This module MIRRORS the E5 decision-receipts issuer's schema in-repo
(schema ``e5.decision_receipt.v1`` / ``e5.receipt_checkpoint.v1``, DSSE
envelope shape, canonical JSON, sha256 Merkle tree with odd-leaf
duplication) without importing it: the hackathon repo is public and
self-contained, and the issuer is the production backend behind this
same seam. When Chancellor graduates, gate receipts mint through the issuer
unchanged — the field set decided here is the issuer's field set.

What a chained entry carries beyond the plain audit fields:
  * ``seq``        — the entry's position in the log (0-based);
  * ``prev_hash``  — the previous entry's hash (the chain link);
  * ``entry_hash`` — sha256 over the canonical JSON of the entry body;
  * ``schema``     — ``e5.decision_receipt.v2`` for entries written
    since the frame's adoption (v1 entries are the pre-frame legacy
    form and verify under v1 rules);
  * ``frame_id`` / ``frame_hash`` — the governing frame the entry was
    decided under, cited by identifier and by the frame document's
    sha256, inside the committed body (v2 entries; see FRAME below);
  * ``effect_axes``— AM-2 axes for the gated action (see EFFECT_AXES).

A bare chain misses one attack — tail truncation: drop the last entries
and the remainder is still self-consistent. The defense is a signed
**checkpoint**: a DSSE envelope whose payload commits to ``log_size``
and the Merkle root over all entry hashes. The verifier in
``chancellor.verify_log`` re-walks everything offline and names the exact
failure.

Checkpoint **v2** (``e5.receipt_checkpoint.v2``) repairs the v1 tree's
anchor-layer defect — odd-leaf duplication makes root([a,b,c]) equal
root([a,b,c,c]), so a bare anchored root never committed to the count —
with the RFC 9162 construction (domain-separated, no duplication), a
count-binding anchor digest, and standalone holder-presented inclusion
proofs. v1 checkpoints keep verifying under v1 rules (dual-verify).

SIGNER HONESTY: Python's stdlib has no Ed25519, so the default signer
here is :class:`DevHmacSigner` — HMAC-SHA256 with a clearly-marked,
well-known dev secret. Dev checkpoints prove internal consistency for
the demo; they are NOT third-party non-repudiation. Production signs
through the E5 issuer's separated Ed25519 signer service
(``did:e5key``) behind this same :class:`Signer` interface.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

SCHEMA_V1 = "e5.decision_receipt.v1"
SCHEMA = "e5.decision_receipt.v2"
CHECKPOINT_SCHEMA = "e5.receipt_checkpoint.v1"
CHECKPOINT_SCHEMA_V2 = "e5.receipt_checkpoint.v2"
PAYLOAD_TYPE = "application/vnd.e5.decision-receipt.v1+json"
CHECKPOINT_PAYLOAD_TYPE = "application/vnd.e5.receipt-checkpoint.v1+json"
CHECKPOINT_PAYLOAD_TYPE_V2 = "application/vnd.e5.receipt-checkpoint.v2+json"
TREE_RFC9162 = "rfc9162"

# ------------------------------------------------------------- the frame
# Frame-named receipts (Council M6, ADAPT — pattern after LaSalle/CAPPZ
# PrinciplesChainlet invocation records; Thoth's placement adopted):
# every NEW receipt and gate verdict names the governing frame it was
# decided under — frame_id + frame_hash as fields of the entry body,
# inside the hash-committed, checkpoint-sealed payload, never sidecar
# metadata. A decision that cannot name its governing text is a quote
# without a source; a verdict under frame v1 is never silently re-read
# under v2.
#
# The frame document is docs/governance-frame.md. FRAME_HASH is the
# sha256 over that document's exact bytes, and a test recomputes it —
# amending the document without amending this registry fails the gate.
# Amending the frame is a visible act: new version, new hash — and the
# OLD pair stays in KNOWN_FRAMES forever (an appended act, never an
# erasure), so receipts issued under a superseded frame still verify.
FRAME_ID = "e5.chancellor_frame.v2"
FRAME_HASH = "3510dd4536e28c109269e627d467d3e6fdb829992733095156d305edd634409e"
FRAME_DOCUMENT = "docs/governance-frame.md"

# The v1 pair is retained verbatim forever: receipts issued under v1
# keep citing it and remain verifiable (the frame's own amendment
# rule — an appended act, never an erasure).
KNOWN_FRAMES: dict[str, str] = {
    "e5.chancellor_frame.v1": (
        "2c57e4e50af380eceb8c4256be71221fca1c1e2814e3d5e623b1a5a177458749"
    ),
    FRAME_ID: FRAME_HASH,
}


def current_frame_fields() -> dict[str, str]:
    """The frame citation stamped into every new receipt and verdict."""
    return {"frame_id": FRAME_ID, "frame_hash": FRAME_HASH}


def frame_known(frame_id: object, frame_hash: object) -> bool:
    """True iff (frame_id, frame_hash) names a frame this build holds
    in its registry — the verifier's side of the citation."""
    return (
        isinstance(frame_id, str)
        and isinstance(frame_hash, str)
        and KNOWN_FRAMES.get(frame_id) == frame_hash
    )


# --------------------------------------------------------------------- AM-2
# Effect axes (Council AM-2): an action carries every axis it truly has;
# the gate fires if ANY axis is present; the receipt records the axes
# alongside the legacy action class.
AXIS_MONEY_MOVEMENT = "money_movement"
AXIS_EXTERNAL_VISIBILITY = "external_visibility"
AXIS_IRREVERSIBILITY = "irreversibility"
AXIS_CREDENTIAL_EXPOSURE = "credential_exposure"

EFFECT_AXES: dict[str, tuple[str, ...]] = {
    "read": (),
    "draft": (),
    "compute": (),
    "spend": (AXIS_MONEY_MOVEMENT,),
    "external_send": (AXIS_EXTERNAL_VISIBILITY,),
    "publish": (AXIS_EXTERNAL_VISIBILITY, AXIS_IRREVERSIBILITY),
    "irreversible": (AXIS_IRREVERSIBILITY,),
    "credential": (AXIS_CREDENTIAL_EXPOSURE,),
    # Capability install (frame v2, clause 6): no axis of its own on
    # the static floor — a governed bundle's own permissions enter
    # through the AM-2 request-side seam (chancellor.escalation),
    # unioned over this empty floor at record time.
    "capability_install": (),
}


def effect_axes_for(action_class_value: str) -> list[str]:
    """Axes for an ActionClass value string; unknown classes get none
    here — class validation itself is the gatekeeper's job (Lane 1)."""
    return list(EFFECT_AXES.get(action_class_value, ()))


# --------------------------------------------------------------------- algebra
def canonical(obj) -> bytes:
    """Sorted keys, compact separators, raw UTF-8 — byte-identical to
    the issuer's canonical form for the value shapes this schema carries."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """SHA-256 of data, hex-encoded — the chain's one hash, named once."""
    return hashlib.sha256(data).hexdigest()


def entry_hash(entry_body: dict) -> str:
    """Hash of a chained entry: sha256 over canonical JSON of the entry
    WITHOUT its ``entry_hash`` field (every other field is committed)."""
    body = {k: v for k, v in entry_body.items() if k != "entry_hash"}
    return sha256_hex(canonical(body))


def legacy_anchor(prev_entry: dict) -> str:
    """Chain anchor for the first chained entry after an unchained
    legacy prefix: sha256 over the canonical form of the last legacy
    entry as parsed. Binds the chain to the legacy tail so editing a
    legacy line breaks the first link."""
    return sha256_hex(canonical(prev_entry))


def merkle_root(leaf_hashes: list[str]) -> str:
    """Binary sha256 Merkle root over hex leaf hashes (odd leaf promoted
    by duplication — the issuer's construction)."""
    if not leaf_hashes:
        return sha256_hex(b"")
    level = [bytes.fromhex(h) for h in leaf_hashes]
    while len(level) > 1:
        nxt = []
        for i in range(0, len(level), 2):
            left = level[i]
            right = level[i + 1] if i + 1 < len(level) else left
            nxt.append(hashlib.sha256(left + right).digest())
        level = nxt
    return level[0].hex()


# ------------------------------------------------------- Merkle, v2
# Checkpoint v2 (mirrors the issuer's e5.receipt_checkpoint.v2): the v1
# tree promotes an odd leaf by duplication, so root([a,b,c]) ==
# root([a,b,c,c]) — a bare root does not commit to the log size. The v2
# construction is RFC 9162: domain-separated hashing (leaves
# SHA256(0x00 || leaf), inner SHA256(0x01 || left || right)), split at
# the largest power of two below n, NO duplication — every tree size
# has a distinct root, and the anchor digest binds the count with it.


def _largest_pow2_below(n: int) -> int:
    """Largest power of two strictly below n (n >= 2)."""
    k = 1
    while k * 2 < n:
        k *= 2
    return k


def _rfc9162_leaf(data: bytes) -> bytes:
    return hashlib.sha256(b"\x00" + data).digest()


def _rfc9162_inner(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(b"\x01" + left + right).digest()


def _rfc9162_mth(leaves: list[bytes]) -> bytes:
    """Merkle Tree Hash over raw leaf bytes (RFC 9162 §2.1)."""
    n = len(leaves)
    if n == 0:
        return hashlib.sha256(b"").digest()
    if n == 1:
        return _rfc9162_leaf(leaves[0])
    k = _largest_pow2_below(n)
    return _rfc9162_inner(_rfc9162_mth(leaves[:k]), _rfc9162_mth(leaves[k:]))


def rfc9162_root(leaf_hashes: list[str]) -> str:
    """RFC 9162 Merkle root over hex leaf hashes. No duplication:
    roots for different sizes never collide by construction."""
    return _rfc9162_mth([bytes.fromhex(h) for h in leaf_hashes]).hex()


def _rfc9162_path(leaves: list[bytes], index: int) -> list[bytes]:
    """Inclusion path for `index` (RFC 9162 §2.1.1 PATH), bottom-up."""
    n = len(leaves)
    if n == 1:
        return []
    k = _largest_pow2_below(n)
    if index < k:
        return _rfc9162_path(leaves[:k], index) + [_rfc9162_mth(leaves[k:])]
    return _rfc9162_path(leaves[k:], index - k) + [_rfc9162_mth(leaves[:k])]


def rfc9162_proof(leaf_hashes: list[str], index: int) -> dict:
    """A standalone, holder-presentable inclusion proof:
    {leaf_hash, index, tree_size, path: [hex, ...]} — carries the tree
    size a verifier needs, without the log."""
    leaves = [bytes.fromhex(h) for h in leaf_hashes]
    if not 0 <= index < len(leaves):
        raise ValueError(f"index {index} outside tree of {len(leaves)}")
    return {
        "leaf_hash": leaf_hashes[index],
        "index": index,
        "tree_size": len(leaves),
        "path": [p.hex() for p in _rfc9162_path(leaves, index)],
    }


def _rfc9162_root_from_proof(
    leaf: bytes, index: int, tree_size: int, path: list[bytes]
) -> bytes | None:
    """Fold a proof back to a candidate root, mirroring _rfc9162_path's
    recursion exactly. None if the path length mismatches the shape."""
    pos = 0

    def fold(idx: int, n: int) -> bytes | None:
        nonlocal pos
        if n == 1:
            return _rfc9162_leaf(leaf)
        k = _largest_pow2_below(n)
        if idx < k:
            sub = fold(idx, k)
            if sub is None or pos >= len(path):
                return None
            sib = path[pos]
            pos += 1
            return _rfc9162_inner(sub, sib)
        sub = fold(idx - k, n - k)
        if sub is None or pos >= len(path):
            return None
        sib = path[pos]
        pos += 1
        return _rfc9162_inner(sib, sub)

    root = fold(index, tree_size)
    if root is None or pos != len(path):
        return None
    return root


def rfc9162_verify(
    leaf_hex: str,
    index: int,
    tree_size: int,
    path: list[str],
    root_hex: str,
) -> bool:
    """Verify a holder-presented inclusion proof against a root using
    ONLY the proof object — never the full log. Fail-closed."""
    try:
        leaf = bytes.fromhex(leaf_hex)
        path_b = [bytes.fromhex(p) for p in path]
        root = bytes.fromhex(root_hex)
    except (ValueError, TypeError):
        return False
    if len(leaf) != 32 or len(root) != 32:
        return False
    if any(len(p) != 32 for p in path_b):
        return False
    if tree_size < 1 or not 0 <= index < tree_size:
        return False
    got = _rfc9162_root_from_proof(leaf, index, tree_size, path_b)
    return got is not None and got == root


def checkpoint_anchor_digest(payload: dict) -> str:
    """The v2 external-anchor digest: sha256 over the canonical
    checkpoint payload — one digest committing to merkle_root +
    log_size + head_receipt_hash together (count-in-anchor)."""
    return sha256_hex(canonical(payload))


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding (in-toto/DSSE standard),
    mirroring the issuer."""
    pt = payload_type.encode("utf-8")
    return (
        b"DSSEv1 "
        + str(len(pt)).encode()
        + b" "
        + pt
        + b" "
        + str(len(payload)).encode()
        + b" "
        + payload
    )


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


# --------------------------------------------------------------------- signer
class Signer(Protocol):
    """Anything that can sign checkpoint payloads. The production
    implementation is the E5 issuer's signer service (Ed25519,
    payload-in/signature-out, key held apart from the log)."""

    key_id: str

    def sign(self, data: bytes) -> bytes: ...

    def verify(self, data: bytes, sig: bytes) -> bool: ...


# DEV ONLY — a well-known secret, printed here on purpose. Anyone can
# recompute these signatures; that is fine for a self-contained demo
# and worthless for production. Override via CHANCELLOR_DEV_SIGNER_SECRET
# for a marginally-less-public dev secret; graduate to the issuer
# signer for anything real.
DEV_SIGNER_SECRET = b"CHANCELLOR-DEV-SIGNER-NOT-A-REAL-KEY"
DEV_SIGNER_KEY_ID = "chancellor-dev-hmac-sha256"


class DevHmacSigner:
    """HMAC-SHA256 dev signer. See module docstring: consistency
    evidence for the demo, never non-repudiation."""

    key_id = DEV_SIGNER_KEY_ID

    def __init__(self, secret: bytes | None = None):
        if secret is None:
            env = os.environ.get("CHANCELLOR_DEV_SIGNER_SECRET")
            secret = env.encode("utf-8") if env else DEV_SIGNER_SECRET
        self._secret = secret

    def sign(self, data: bytes) -> bytes:
        return hmac.new(self._secret, data, hashlib.sha256).digest()

    def verify(self, data: bytes, sig: bytes) -> bool:
        return hmac.compare_digest(self.sign(data), sig)


def default_signer() -> Signer:
    """The development signer. A demo credential by design; production
    custody replaces it, not extends it."""
    return DevHmacSigner()


# --------------------------------------------------------------------- checkpoint
def build_checkpoint(
    *,
    signer: Signer,
    log_size: int,
    leaves: list[str],
    head_hash: str | None,
    created_at: int | None = None,
) -> dict:
    """A signed Merkle checkpoint as a DSSE envelope, payload shaped
    exactly like the issuer's ``e5.receipt_checkpoint.v1``:
    {schema, issuer, created_at, log_size, merkle_root,
    head_receipt_hash}."""
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "issuer": signer.key_id,
        "created_at": int(time.time()) if created_at is None else created_at,
        "log_size": log_size,
        "merkle_root": merkle_root(leaves),
        "head_receipt_hash": head_hash,
    }
    sig = signer.sign(pae(CHECKPOINT_PAYLOAD_TYPE, canonical(payload)))
    return {
        "payloadType": CHECKPOINT_PAYLOAD_TYPE,
        "payload": _b64(canonical(payload)),
        "signatures": [{"keyid": signer.key_id, "sig": _b64(sig)}],
    }


def build_checkpoint_v2(
    *,
    signer: Signer,
    log_size: int,
    leaves: list[str],
    head_hash: str | None,
    created_at: int | None = None,
) -> dict:
    """A signed checkpoint under ``e5.receipt_checkpoint.v2``: payload
    shaped like v1 plus ``tree: "rfc9162"``, root computed by the
    RFC 9162 construction. The digest meant for external anchoring is
    :func:`checkpoint_anchor_digest` over this payload — count and
    root committed together, where v1's bare root committed to neither
    the count nor (by duplication) even the size."""
    payload = {
        "schema": CHECKPOINT_SCHEMA_V2,
        "issuer": signer.key_id,
        "created_at": int(time.time()) if created_at is None else created_at,
        "log_size": log_size,
        "merkle_root": rfc9162_root(leaves),
        "head_receipt_hash": head_hash,
        "tree": TREE_RFC9162,
    }
    sig = signer.sign(pae(CHECKPOINT_PAYLOAD_TYPE_V2, canonical(payload)))
    return {
        "payloadType": CHECKPOINT_PAYLOAD_TYPE_V2,
        "payload": _b64(canonical(payload)),
        "signatures": [{"keyid": signer.key_id, "sig": _b64(sig)}],
    }


def checkpoint_payload(envelope: dict) -> dict:
    """Decode a checkpoint envelope's payload back to its dict."""
    return json.loads(_unb64(envelope["payload"]).decode("utf-8"))


def checkpoint_signature_valid(envelope: dict, signer: Signer) -> bool:
    """True iff a checkpoint envelope carries a valid signature under
    signer. Fail-closed: any malformation reads False."""
    try:
        payload_bytes = _unb64(envelope["payload"])
        sigs = envelope["signatures"]
        if len(sigs) != 1 or sigs[0]["keyid"] != signer.key_id:
            return False
        return signer.verify(
            pae(envelope["payloadType"], payload_bytes), _unb64(sigs[0]["sig"])
        )
    except Exception:
        return False


# ------------------------------------------------- freeze / test-run entries
# RepoZ-shaped provenance records (CAPPZ delta REA §4.3, pattern-level):
# a freeze manifest and the test runs that vouch for it are entries in
# this same chain, not sidecar documents — so a reader can RESOLVE from
# a manifest hash to its covering test runs and the checkpoint that
# seals them (see chancellor.verify_log.resolve_manifest) instead of
# trusting a filing cabinet of separate reports.
ENTRY_TYPE_FREEZE_MANIFEST = "freeze_manifest"
ENTRY_TYPE_TEST_RUN = "test_run"

_HEX64 = frozenset("0123456789abcdef")


def _require_sha256(value: object, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(c not in _HEX64 for c in value)
    ):
        raise ValueError(f"{field_name} must be a lowercase sha256 hex digest")
    return value


def compute_manifest_sha256(files: dict[str, str]) -> str:
    """The manifest hash: sha256 over the canonical JSON of the sealed
    file list itself ({relpath: sha256}). The list IS the manifest; its
    hash is the identity every test_run binds to."""
    if not isinstance(files, dict) or not files:
        raise ValueError("files must be a non-empty {relpath: sha256} mapping")
    for relpath, digest in files.items():
        if not isinstance(relpath, str) or not relpath:
            raise ValueError("manifest relpaths must be non-empty strings")
        _require_sha256(digest, f"files[{relpath!r}]")
    return sha256_hex(canonical({"files": files}))


def freeze_manifest_fields(
    *,
    files: dict[str, str],
    suite_id: str,
    head: str | None,
    recorded_by: str,
    ts: float | None = None,
) -> dict:
    """Field body for a freeze_manifest entry (chain fields — schema,
    seq, prev_hash, entry_hash — are stamped by the appending log).
    Carries the sealed file list itself plus its hash, the suite the
    freeze belongs to, and the repo head it seals."""
    if not isinstance(suite_id, str) or not suite_id:
        raise ValueError("suite_id must be a non-empty string")
    if not isinstance(recorded_by, str) or not recorded_by:
        raise ValueError("recorded_by must be a non-empty string")
    return {
        "entry_type": ENTRY_TYPE_FREEZE_MANIFEST,
        "ts": time.time() if ts is None else ts,
        "manifest_sha256": compute_manifest_sha256(files),
        "files": dict(files),
        "file_count": len(files),
        "suite_id": suite_id,
        "head": head,
        "recorded_by": recorded_by,
    }


def test_run_fields(
    *,
    suite: str,
    command: str,
    manifest_sha256: str,
    report_sha256: str,
    passed: int,
    failed: int,
    seat: str,
    report_path: str | None = None,
    ts: float | None = None,
) -> dict:
    """Field body for a test_run entry: the run binds the manifest hash
    it ran against, the suite/command, the report's sha256, the
    pass/fail counts, and the seat that ran it."""
    for name, value in (("suite", suite), ("command", command), ("seat", seat)):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
    for name, count_value in (("passed", passed), ("failed", failed)):
        if (
            not isinstance(count_value, int)
            or isinstance(count_value, bool)
            or count_value < 0
        ):
            raise ValueError(f"{name} must be a non-negative int")
    return {
        "entry_type": ENTRY_TYPE_TEST_RUN,
        "ts": time.time() if ts is None else ts,
        "suite": suite,
        "command": command,
        "manifest_sha256": _require_sha256(manifest_sha256, "manifest_sha256"),
        "report_sha256": _require_sha256(report_sha256, "report_sha256"),
        "report_path": report_path,
        "passed": passed,
        "failed": failed,
        "seat": seat,
    }


# ------------------------------------------------- capability-install entries
# Frame v2, clause 6 (growth is governed): the install arc's own
# entries in this same chain — probation opened on Beat-2 passage,
# probation closed at the window's end, suspension on strikes, and a
# use record for every auto-approved invocation of a probationary
# capability (gated-class uses are their gate Decisions; see
# chancellor.installs). The fold over these entries IS the probation
# state: nothing about a capability's standing lives anywhere else.
ENTRY_TYPE_CAPABILITY_PROBATION_OPENED = "capability_probation_opened"
ENTRY_TYPE_CAPABILITY_PROBATION_CLOSED = "capability_probation_closed"
ENTRY_TYPE_CAPABILITY_SUSPENSION = "capability_suspension"
ENTRY_TYPE_CAPABILITY_USE = "capability_use"

# The probationary window (spec §2 P1): counted in receipted uses.
PROBATION_WINDOW_USES = 10

# The closed suspension-reason vocabulary: two graded strikes inside
# the window, or a single one-strike event (pin drift at fold time,
# an out-of-permission action).
SUSPENSION_REASON_TWO_STRIKES = "two-strikes"
SUSPENSION_REASON_PIN_DRIFT = "pin-drift"
SUSPENSION_REASON_OUT_OF_PERMISSION = "out-of-permission"
CAPABILITY_SUSPENSION_REASONS: frozenset[str] = frozenset(
    {
        SUSPENSION_REASON_TWO_STRIKES,
        SUSPENSION_REASON_PIN_DRIFT,
        SUSPENSION_REASON_OUT_OF_PERMISSION,
    }
)

CAPABILITY_GRADES: frozenset[str] = frozenset({"pass", "fail"})


def _require_pin(value: object, field_name: str) -> str:
    """A Foundry whole-tree manifest pin: 'sha256:' + 64 lowercase hex
    (the manager's pin format — cited verbatim across the bridge,
    never translated)."""
    if not isinstance(value, str) or not value.startswith("sha256:"):
        raise ValueError(f"{field_name} must be a 'sha256:'-prefixed pin")
    _require_sha256(value[len("sha256:") :], field_name)
    return value


def _require_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


def _require_count(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative int")
    return value


def capability_probation_opened_fields(
    *,
    capability_id: str,
    manifest_pin: str,
    decision_seq: int,
    decision_entry_hash: str,
    install_receipt_id: str,
    beat2_report_hash: str,
    commission_receipt_id: str,
    window_uses: int = PROBATION_WINDOW_USES,
    ts: float | None = None,
) -> dict:
    """Field body for a capability_probation_opened entry: written
    when Beat 2 (verified-live, by a reader who did not install)
    passes. Cites the Step-3 gate decision by chain seq + entry
    hash, the issuer install receipt, the Beat-2 report's hash, and
    the commission the arc runs under — the whole correspondence a
    bridge audit needs, by hash and id, never by paraphrase."""
    return {
        "entry_type": ENTRY_TYPE_CAPABILITY_PROBATION_OPENED,
        "ts": time.time() if ts is None else ts,
        "capability_id": _require_id(capability_id, "capability_id"),
        "manifest_pin": _require_pin(manifest_pin, "manifest_pin"),
        "decision_seq": _require_count(decision_seq, "decision_seq"),
        "decision_entry_hash": _require_sha256(
            decision_entry_hash, "decision_entry_hash"
        ),
        "install_receipt_id": _require_sha256(
            install_receipt_id, "install_receipt_id"
        ),
        "beat2_report_hash": _require_sha256(
            beat2_report_hash, "beat2_report_hash"
        ),
        "commission_receipt_id": _require_sha256(
            commission_receipt_id, "commission_receipt_id"
        ),
        "window_uses": _require_count(window_uses, "window_uses"),
    }


def capability_probation_closed_fields(
    *,
    capability_id: str,
    manifest_pin: str,
    uses: int,
    strikes: int,
    ts: float | None = None,
) -> dict:
    """Field body for a capability_probation_closed entry: standing
    earned at the window's end. The strike count is printed —
    standing is not amnesia."""
    return {
        "entry_type": ENTRY_TYPE_CAPABILITY_PROBATION_CLOSED,
        "ts": time.time() if ts is None else ts,
        "capability_id": _require_id(capability_id, "capability_id"),
        "manifest_pin": _require_pin(manifest_pin, "manifest_pin"),
        "uses": _require_count(uses, "uses"),
        "strikes": _require_count(strikes, "strikes"),
    }


def capability_suspension_fields(
    *,
    capability_id: str,
    manifest_pin: str,
    strike_seqs: list[int],
    reason: str,
    ts: float | None = None,
) -> dict:
    """Field body for a capability_suspension entry: the first of the
    suspension's three same-motion records (suspension entry →
    Foundry disable enforcement → escalation Decision). The strikes
    are cited by chain seq."""
    if reason not in CAPABILITY_SUSPENSION_REASONS:
        raise ValueError(
            f"reason must be one of {sorted(CAPABILITY_SUSPENSION_REASONS)}"
        )
    if not strike_seqs:
        raise ValueError("strike_seqs must name at least one strike")
    return {
        "entry_type": ENTRY_TYPE_CAPABILITY_SUSPENSION,
        "ts": time.time() if ts is None else ts,
        "capability_id": _require_id(capability_id, "capability_id"),
        "manifest_pin": _require_pin(manifest_pin, "manifest_pin"),
        "strike_seqs": [
            _require_count(s, "strike_seqs[]") for s in strike_seqs
        ],
        "reason": reason,
    }


def capability_use_fields(
    *,
    capability_id: str,
    manifest_pin: str,
    invocation: str,
    grade: str | None = None,
    out_of_permission: bool = False,
    pin_drift: bool = False,
    ts: float | None = None,
) -> dict:
    """Field body for a capability_use entry: one receipted use of a
    probationary capability through the auto-approved path (read /
    draft / compute invocations via the authoring loop or the
    manager's query path). The grade rides the record where a grader
    graded the use; pin_drift is stamped when the fold-time census
    pin disagreed with the probation pin at this use."""
    if grade is not None and grade not in CAPABILITY_GRADES:
        raise ValueError(f"grade must be one of {sorted(CAPABILITY_GRADES)}")
    return {
        "entry_type": ENTRY_TYPE_CAPABILITY_USE,
        "ts": time.time() if ts is None else ts,
        "capability_id": _require_id(capability_id, "capability_id"),
        "manifest_pin": _require_pin(manifest_pin, "manifest_pin"),
        "invocation": _require_id(invocation, "invocation"),
        "grade": grade,
        "out_of_permission": bool(out_of_permission),
        "pin_drift": bool(pin_drift),
    }


# --------------------------------------------------------------------- chain errors
class ChainIntegrityError(RuntimeError):
    """Raised when an existing log's chained entries fail verification
    at open time — a tampered log accepts no new receipts."""


@dataclass
class ChainState:
    """Rebuilt-by-reading state of a chained log file."""

    total_entries: int = 0  # every line, legacy + chained
    chained: int = 0  # entries carrying entry_hash
    legacy_prefix: int = 0  # unchained lines before the chain starts
    prev_hash: str | None = None  # link the next entry must carry
    leaves: list[str] = field(default_factory=list)  # chained entry hashes


# CC 11 (radon) — a linear walk over the chain; one branch per
# defect class the scan must classify.
def scan_chain(lines: list[dict]) -> ChainState:
    """Walk parsed log lines and rebuild chain state, VERIFYING as we
    go. Raises ChainIntegrityError naming the first break."""
    state = ChainState()
    prev_entry: dict | None = None
    for pos, entry in enumerate(lines):
        state.total_entries += 1
        if "entry_hash" not in entry:
            if state.chained:
                raise ChainIntegrityError(
                    f"unchained entry at position {pos} after the chain "
                    f"has started — log is not append-only"
                )
            state.legacy_prefix += 1
            prev_entry = entry
            continue
        expected_prev = (
            legacy_anchor(prev_entry)
            if state.chained == 0 and prev_entry is not None
            else state.prev_hash
        )
        if entry.get("seq") != pos:
            raise ChainIntegrityError(
                f"seq mismatch at position {pos}: entry claims seq={entry.get('seq')!r}"
            )
        if entry.get("prev_hash") != expected_prev:
            raise ChainIntegrityError(f"prev_hash link broken at seq {pos}")
        if entry_hash(entry) != entry["entry_hash"]:
            raise ChainIntegrityError(
                f"entry_hash mismatch at seq {pos} — entry was edited"
            )
        state.chained += 1
        state.leaves.append(entry["entry_hash"])
        state.prev_hash = entry["entry_hash"]
        prev_entry = entry
    if state.chained == 0 and prev_entry is not None:
        # Legacy-only file: the next entry anchors to the legacy tail.
        state.prev_hash = legacy_anchor(prev_entry)
    return state


def default_checkpoint_path(log_path: str | Path) -> Path:
    """A log's checkpoint sidecar lives beside it, at '<log>.checkpoints.jsonl'."""
    return Path(str(log_path) + ".checkpoints.jsonl")
