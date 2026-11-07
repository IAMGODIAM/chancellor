"""Throwaway operator signer for tests that exercise the pinned-verifier
path. The secret is created here for the tests only; it is not a real key."""

import base64
import hashlib
import os

from chancellor import receipts

OPERATOR_SECRET = "throwaway-operator-secret-for-tests-0123456789"


def operator_signer() -> receipts.HmacSigner:
    return receipts.HmacSigner(secret=OPERATOR_SECRET.encode("utf-8"))


def pin_args(monkeypatch) -> list[str]:
    """CLI arguments pinning the operator signer; the verifying secret is
    supplied through the environment, as the verifier expects."""
    monkeypatch.setenv(receipts.VERIFY_KEY_ENV, OPERATOR_SECRET)
    return ["--pubkey", operator_signer().key_id]


# ---- a throwaway Ed25519 key, made inside the test run -------------------
# The product ships a verifier for a pinned Ed25519 public key and no
# signer. Tests need something to sign with, so this is the RFC 8032
# reference construction over the product's own curve arithmetic. Keys
# come from os.urandom per call and are never written anywhere.
def _compress(point) -> bytes:
    zinv = pow(point[2], receipts._P - 2, receipts._P)
    x = point[0] * zinv % receipts._P
    y = point[1] * zinv % receipts._P
    return (y | ((x & 1) << 255)).to_bytes(32, "little")


class Ed25519TestSigner:
    def __init__(self, seed: bytes | None = None):
        self._seed = seed if seed is not None else os.urandom(32)
        digest = hashlib.sha512(self._seed).digest()
        scalar = int.from_bytes(digest[:32], "little")
        scalar &= (1 << 254) - 8
        scalar |= 1 << 254
        self._scalar = scalar
        self._prefix = digest[32:]
        self.public_key = _compress(receipts._point_mul(scalar, receipts.ED25519_BASE))
        self.key_id = receipts.ed25519_key_id(self.public_key)

    @property
    def public_text(self) -> str:
        return "ed25519:" + base64.b64encode(self.public_key).decode("ascii")

    def sign(self, data: bytes) -> bytes:
        order = receipts._L
        r = int.from_bytes(hashlib.sha512(self._prefix + data).digest(), "little")
        r %= order
        big_r = _compress(receipts._point_mul(r, receipts.ED25519_BASE))
        k = int.from_bytes(
            hashlib.sha512(big_r + self.public_key + data).digest(), "little"
        )
        s = (r + (k % order) * self._scalar) % order
        return big_r + s.to_bytes(32, "little")

    def verify(self, data: bytes, sig: bytes) -> bool:
        return receipts.ed25519_verify(self.public_key, data, sig)
