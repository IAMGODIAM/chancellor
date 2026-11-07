# The open register

What is undecided in this project, written down in one place — as of
**2026-11-01**. An item stands here until it is decided, and the decision,
when it lands, replaces the entry rather than erasing it. Nothing on this
list is hidden anywhere else in the repository; where another document
carries the detail, this register points at it.

## Calibration — remedy-2

**Status: unruled.** The Suite A calibration gate has been run twice
under pre-registration and has not passed (see the Results section of
the README and BUILD-LOG.md). A third attempt — remedy-2 — would need a
fresh pre-registration written before the run and the entrant's explicit
ruling to proceed. Until both exist, no attempt is made and no Suite A
score is claimed; live judge verdicts ship labeled *uncalibrated*.

## Production signer separation

**Status: named, not built.** The audit chain's checkpoints are signed
with a development signer whose key ships in the source, deliberately
public and labeled in the code. Those signatures carry tamper-evidence
and internal consistency, not non-repudiation. Before any deployment
that needs attribution, the signer must be separated — a production key
held apart from the code (HSM/KMS class). This is the named hardening
step; it is not done, and this register is where that fact stands.

## Hindcast — the scorer's chair

**Status: deliberately empty.** The hindcast bank (sealed historical
cases, replayed against the harness) has pilot cases filed and its
scorer slot unfilled *by design*: predictor, runner, and scorer are
different chairs, and no one in the current team may hold the scorer's.
No replay runs until a scorer is named and the bank reaches 10 cases.
Until then hindcast is charter, not results, and is reported that way.

## The demo film — upgraded cut

**Status: in production.** The film linked in the README's Demo section
is the verified capture cut. A commercial-quality upgrade — generated
visuals in the direction of a world running under governance — is in
production at the creative desk. If it lands before submission it
replaces the link; the current film remains a true capture of the
product either way, and nothing in the submission waits on the upgrade.

## Pull requests #2 and #3

**Status: held, in sequence.** PR #2 (the bridge documents) merges
first, PR #3 (the independent study dossier, reviewed and accepted)
second — both after the submission freeze lifts, so the tree the judges
were pointed at is the tree that was measured. The sequence is the
decision; the merges are bookkeeping that follows it.

## Live capture, under custody

**Status: declined, on the record.** Tooling is demonstrated in this
submission through the offline path; the live Meta-model path is
transport-validated but not captured in a run artifact. The reason is a
custody rule, and it is stated in full in BUILD-LOG.md (the RT-4
disposition): the API credential never sits in an environment variable,
so the env-fed live mode cannot be exercised for a capture without
breaking the discipline the project exists to demonstrate. The gap is
named here so it is a decision, not an omission.

## Capability install

**Status: built and measured.** The ninth gated act class — an agent
gaining a new capability as a proposed, checked, gate-decided,
receipted, independently verified, probationary, reversible act —
is built on this tree (frame v2, `src/chancellor/installs.py`,
specified in docs/foundry-install-spec.md) against governed install
machinery already running in the entrant's wider multi-agent
programme. The pre-registered install hearing passed (claims F1–F8)
on the doc-only Phase-0 perimeter; the full record is filed at
docs/evidence/foundry-install-hearing/. The licence is exactly that
perimeter: the connector and schedule kinds, executable payloads,
cost-bearing bundles, and the Prometheus layer remain designed, not
built, under this frame — each a separate gated build.
