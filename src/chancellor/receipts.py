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
  * ``schema``     — ``e5.decision_receipt.v1``;
  * ``effect_axes``— AM-2 axes for the gated action (see EFFECT_AXES).

A bare chain misses one attack — tail truncation: drop the last entries
and the remainder is still self-consistent. The defense is a signed
**checkpoint**: a DSSE envelope whose payload commits to ``log_size``
and the Merkle root over all entry hashes. The verifier in
``chancellor.verify_log`` re-walks everything offline and names the exact
failure.

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

SCHEMA = "e5.decision_receipt.v1"
CHECKPOINT_SCHEMA = "e5.receipt_checkpoint.v1"
PAYLOAD_TYPE = "application/vnd.e5.decision-receipt.v1+json"
CHECKPOINT_PAYLOAD_TYPE = "application/vnd.e5.receipt-checkpoint.v1+json"

GENESIS_PREV: str | None = None  # prev_hash of the first chained entry in a fresh log

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
}


def effect_axes_for(action_class_value: str) -> list[str]:
    """Axes for an ActionClass value string; unknown classes get none
    here — class validation itself is the gatekeeper's job (Lane 1)."""
    return list(EFFECT_AXES.get(action_class_value, ()))


# ------------------------------------------------------------------ algebra
def canonical(obj) -> bytes:
    """Sorted keys, compact separators, raw UTF-8 — byte-identical to
    the issuer's canonical form for the value shapes this schema carries."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_hex(data: bytes) -> str:
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


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding (in-toto/DSSE standard),
    mirroring the issuer."""
    pt = payload_type.encode("utf-8")
    return (b"DSSEv1 " + str(len(pt)).encode() + b" " + pt + b" " +
            str(len(payload)).encode() + b" " + payload)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


# ------------------------------------------------------------------- signer
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
    return DevHmacSigner()


# --------------------------------------------------------------- checkpoint
def build_checkpoint(*, signer: Signer, log_size: int,
                     leaves: list[str], head_hash: str | None,
                     created_at: int | None = None) -> dict:
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


def checkpoint_payload(envelope: dict) -> dict:
    return json.loads(_unb64(envelope["payload"]).decode("utf-8"))


def checkpoint_signature_valid(envelope: dict, signer: Signer) -> bool:
    try:
        payload_bytes = _unb64(envelope["payload"])
        sigs = envelope["signatures"]
        if len(sigs) != 1 or sigs[0]["keyid"] != signer.key_id:
            return False
        return signer.verify(pae(envelope["payloadType"], payload_bytes),
                             _unb64(sigs[0]["sig"]))
    except Exception:
        return False


# ------------------------------------------------------------- chain errors
class ChainIntegrityError(RuntimeError):
    """Raised when an existing log's chained entries fail verification
    at open time — a tampered log accepts no new receipts."""


@dataclass
class ChainState:
    """Rebuilt-by-reading state of a chained log file."""
    total_entries: int = 0          # every line, legacy + chained
    chained: int = 0                # entries carrying entry_hash
    legacy_prefix: int = 0          # unchained lines before the chain starts
    prev_hash: str | None = None    # link the next entry must carry
    leaves: list[str] = field(default_factory=list)  # chained entry hashes


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
                    f"has started — log is not append-only")
            state.legacy_prefix += 1
            prev_entry = entry
            continue
        expected_prev = (legacy_anchor(prev_entry)
                         if state.chained == 0 and prev_entry is not None
                         else state.prev_hash)
        if entry.get("seq") != pos:
            raise ChainIntegrityError(
                f"seq mismatch at position {pos}: entry claims "
                f"seq={entry.get('seq')!r}")
        if entry.get("prev_hash") != expected_prev:
            raise ChainIntegrityError(
                f"prev_hash link broken at seq {pos}")
        if entry_hash(entry) != entry["entry_hash"]:
            raise ChainIntegrityError(
                f"entry_hash mismatch at seq {pos} — entry was edited")
        state.chained += 1
        state.leaves.append(entry["entry_hash"])
        state.prev_hash = entry["entry_hash"]
        prev_entry = entry
    if state.chained == 0 and prev_entry is not None:
        # Legacy-only file: the next entry anchors to the legacy tail.
        state.prev_hash = legacy_anchor(prev_entry)
    return state


def default_checkpoint_path(log_path: str | Path) -> Path:
    return Path(str(log_path) + ".checkpoints.jsonl")
