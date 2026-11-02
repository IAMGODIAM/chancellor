# Production signer separation — design specification

> **FENCE — READ FIRST. This document is a DESIGN ONLY.** The
> mechanism family it designs against — device-backed signing keys,
> signed key declarations, local validation of credential
> containers and access control — sits in the named territory of
> **US 11,645,632 B2**, held personally by Derek Norman LaSalle.
> That flag states proximity only; it is not a legal conclusion.
> **Nothing in this document authorizes implementation, code reuse,
> or procurement.** Whether a production signer is ever built, and
> on what terms, belongs to the Chairman's own licensing
> conversation with Derek, which this document does not touch,
> advance, or imply. This document exists so that the design is
> ready — specified, reviewable, and falsifiable — if and when that
> conversation opens the gate.

**Status: DESIGN ONLY** (council record M1/Button 5 — OWNER-GATE).
It discharges the open-register entry "Production signer separation"
by appended disposition: the entry's *named, not built* becomes
*named, designed, not built*. The register entry is replaced by the
decision, never erased.

**Provenance.** The declaration-and-refusal-state shape is borrowed
as inspiration from the graded pattern in the council record (M1):
a signer whose authority is declared in a signed record, verified
offline, with named reasons when trust is refused. The record
fields, state names, and protocol below are Chancellor's own
design, fitted to Chancellor's existing `Signer` Protocol. Where
the pattern is cited, the nod is: *signer-declaration pattern after
LaSalle/CAPPZ KeyZ declarations and device-signed receipts
(HARDWARE_TRUST §§1–2, 4)*.

## 1. The problem, as the register states it

Every checkpoint Chancellor signs today is signed by
`DevHmacSigner`: an HMAC-SHA256 signer whose secret is printed in
the source, on purpose (`receipts.py`, key ID
`chancellor-dev-hmac-sha256`). Anyone can recompute those
signatures. That is a deliberate, honest posture for a
self-contained demonstration — the signatures prove the chain is
internally consistent and unaltered *relative to itself*
(tamper-evidence), and the code says so in plain words. What they
can never prove is *who* signed: with a public key, attribution is
vacuous (no non-repudiation). Before any deployment that needs
attribution — a receipt a third party must be able to credit to
Chancellor and no one else — the signer must be separated: a
production key, held apart from the code, that the code can ask to
sign but can never read.

## 2. What already fits

The separation point already exists. `receipts.py` defines:

```python
class Signer(Protocol):
    key_id: str

    def sign(self, data: bytes) -> bytes: ...
    def verify(self, data: bytes, sig: bytes) -> bool: ...
```

`DevHmacSigner` is one implementation; the module's own docstring
names the intended production shape — an issuer signer service,
Ed25519, payload-in/signature-out, key held apart from the log,
exposed behind this same interface (`did:e5key`). This design
therefore changes no call sites: `build_checkpoint`,
`checkpoint_signature_valid`, `AuditLog`, and `verify_log` already
talk only to the Protocol. The design's work is everything *around*
the signer: how a verifier knows which signer it is trusting, on
what terms, and what it says when it refuses.

## 3. The signer-declaration record

A production signer does not arrive as a bare key. It arrives with
a **declaration**: a signed record, published with the receipts it
covers, that states the terms under which its signatures should be
trusted. Schema name reserved: `e5.signer_declaration.v1`. Fields:

| Field | Type | Semantics |
|---|---|---|
| `schema` | string | `e5.signer_declaration.v1`. |
| `key_id` | string | The signer's identifier (e.g. a `did:`-style ID). Unique; never reused across keys. |
| `algorithm` | string | Signature algorithm of the declared key (design target: `ed25519`; the declaration, not the verifier's guess, is authoritative). |
| `public_key` | string (base64) | The verification key. Public by design — publication is what makes offline verification possible. |
| `purpose` | string | What this key may sign. Initial vocabulary: `checkpoint` (audit checkpoints), `receipt` (decision receipts), `declaration` (declarations themselves). A key declares the purposes it serves; it does not serve others. |
| `valid_from` | timestamp | Start of the validity window. Signatures over payloads timestamped before this are outside the declaration. |
| `valid_until` | timestamp | End of the validity window. Mandatory — an unbounded declaration is not accepted (§5). |
| `supersedes` | string or null | The `key_id` this declaration rotates away from, if any. Rotation is a new declaration, never an edit. |
| `revocation` | object | `status`: `active` / `revoked`; `revoked_at` (timestamp or null); `reason` (string or null). Revocation is itself a declaration version, appended, never an in-place edit. |
| `custody` | string | Which custody class holds the private key (§6): `hsm`, `kms`, `signer-service`, `device`. Stated so a verifier's operator can weigh it; the verifier does not enforce a class in v1 of this design. |
| `frame_ref` | string | The governing frame identifier + hash in force when the declaration was issued (the frame-named-receipts discipline applied to the signer itself). |
| `signature` | string (base64) | The declaration signed by (a) the declared key itself (proof of possession) and (b) the *introducing* authority — a previously trusted declaration with purpose `declaration`, or, for the root declaration, the project's release-signing path (§6, bootstrap). |

Declarations are append-only records kept beside the audit chain
(same sidecar family as checkpoints), so one cold verification pass
can evaluate every checkpoint against the declaration set in force
at the checkpoint's timestamp.

## 4. The verifier's refusal-state vocabulary

Today `verify_log` answers, in effect, *verified / not verified*.
Under this design the signer layer of verification returns one of
seven named states — our terms, our semantics — and the overall
verification result carries the state verbatim. A verifier that
says *why* it refused produces evidence; one that says "no"
produces an incident (Wolfram's condition, M1).

| State | Meaning |
|---|---|
| `trusted` | Signature valid; declaration active; purpose matches the payload's kind; payload timestamp inside the validity window. |
| `bad-signature` | The signature does not verify against the declared public key. The record is not what it claims to be, independent of any declaration question. |
| `undeclared` | No declaration exists for the `key_id` that signed. A key nobody declared is a key nobody vouched for. |
| `revoked` | The declaration's current version records revocation at or before the verification moment. (Signatures made *before* `revoked_at` are reported as `trusted-at-signing, since-revoked` in the detail line — revocation is not retroactive falsification, and the vocabulary must not pretend it is.) |
| `expired` | The payload's timestamp falls outside `valid_from`–`valid_until`. |
| `wrong-purpose` | The declaration's `purpose` does not cover this payload kind — e.g. a `receipt` key presented over a checkpoint. |
| `not-yet-valid` | The payload predates `valid_from` (kept distinct from `expired`: backdating and staleness are different findings). |

The checkpoint layer's own checks (chain linkage, Merkle root,
entry count) are unchanged and compose multiplicatively: a
checkpoint is verified only when its chain checks pass **and** its
signer state is `trusted` (or the since-revoked detail form, which
the operator's policy — not this design — may accept for historical
logs). With the development signer, verification behavior is
exactly as today: the dev key carries no declaration and the
verifier reports the standing caveat — *tamper-evidence only; the
signing key is public by design* — rather than any of the states
above. The design never lets a dev-signed log borrow the
vocabulary of attribution.

## 5. Rules that bind the design

- **Offline verification is preserved.** A declaration set plus a
  log plus its sidecars is sufficient to verify, cold, with no
  network and no call home. (This is a hard requirement, inherited
  from the product's existing posture: `verify_log` works offline
  today and any signer design that phones home is a regression,
  not a feature.)
- **Declarations are bounded.** Every declaration carries
  `valid_until`; renewal is a new version. No perpetual keys.
- **Rotation is normal.** `supersedes` makes key rotation a
  routine, receipted event rather than an incident; the chain of
  declarations is itself auditable.
- **Revocation is append-only and non-retroactive** (§4). The
  record of what was trusted when is never rewritten.
- **The private key never enters the repo, an environment
  variable, or the audit process's readable memory beyond the sign
  call.** Custody (§6) holds the key; the harness holds a handle.
  (The open register's custody rule for credentials — the reason
  the live capture stands declined — is the same discipline,
  applied here by design rather than discovered by accident.)
- **Dev and production never mix silently.** A log whose
  checkpoints are signed by more than one `key_id` reports each
  signer's spans explicitly; a transition from dev to production
  signing is a checkpointed, receipted event in the log itself.

## 6. Key custody options, with honest trade-offs

| Option | What holds the key | Trade-offs |
|---|---|---|
| **Signer service** (the docstring's named target) | A separate small service — payload in, signature out; key in its own store, ideally backed by an HSM/KMS it alone can call. | Cleanest fit for the Protocol (it already assumes exactly this shape). Costs: a second thing to run and keep alive (the continuity problem recurses one level — the supervisor design's anchoring disclosure applies), and the service becomes a high-value target whose own access must be gated and receipted. |
| **Cloud KMS / HSM direct** | A provider's managed key (AWS KMS, Cloud HSM, Azure Key Vault class); the harness calls the sign API. | Strong custody, audit trails included, no key material anywhere near the code. Costs: a provider dependency and per-call pricing — against this project's $0 / own-the-asset posture, and an external availability dependency for a harness whose offline posture is a feature. Ed25519 support varies by provider and must be checked, not assumed. |
| **Device-held key** (hardware authenticator / secure enclave) | The key lives in a person's device hardware; signing requires human presence at the act. | Strongest attribution story — a signature proves an enrolled device *and* a present human, which is precisely what a human-gate approval wants to be able to say. Costs: signing throughput is human-paced (checkpoints are frequent; approvals are not — this option fits *approval* signing far better than *checkpoint* signing, and a split — service signs checkpoints, device countersigns approvals — is the honest composite); device loss is a revocation drill; and this option sits closest to the flagged patent territory (see the fence). |
| **Operator-held key file, OS-permissioned** | A key file readable only by the service account, outside the repo. | Cheapest and simplest; strictly better than a public key. Weakest of the four: host compromise is key compromise, no presence proof, no hardware boundary. Acceptable only as a transitional step and the design says so. |

**Bootstrap.** The root declaration cannot be introduced by
another declaration. The design's answer: the root declaration is
issued through the project's existing release path (the same
channel that publishes the package — its signing identity is the
trust anchor), and its fingerprint is printed in the release notes
and the BUILD-LOG, so its introduction is a public, dated act
rather than a silent configuration.

## 7. What this design does not do

- It does not select a custody option. That choice has cost and
  licensing dimensions that are the Chairman's.
- It does not specify an implementation, an API beyond the existing
  Protocol, or a timeline.
- It does not change the meaning of any existing signature. Every
  log signed to date remains dev-signed, tamper-evident, and
  honestly labeled — including in the submission in front of the
  judges right now. Separation, if it ever ships, is forward-only.

*Design ends. Implementation is not authorized by this document
and belongs to the Chairman's own licensing conversation (see the
fence at the head of this document).*
