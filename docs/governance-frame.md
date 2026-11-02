# Chancellor Governing Frame

frame_id: e5.chancellor_frame.v2
version: 2

This document is the governing frame under which Chancellor issues
receipts and gate verdicts. Every receipt and verdict recorded since
the frame's adoption cites this frame by identifier and by the
SHA-256 hash of this document, inside the signed payload — so a
decision can always be read against the exact frame version it was
decided under, and never silently re-read under a later one.

Version 2 supersedes version 1 by the frame's own amendment route:
clause 2 now names acts that change what the agent itself can do,
and clause 6 — growth is governed — is added. Receipts issued under
version 1 keep citing it and remain verifiable (see "Amending this
frame").

## The frame

1. **Work is graded.** A consequential output is graded by a judge
   separate from the worker before it stands.
2. **Authority is gated.** Acts that spend money, send externally,
   publish, act irreversibly, use a credential, or change what the
   agent itself can do wait at a human gate. A gate with no human
   attached denies by default: unattended authority is not authority.
3. **Every decision leaves a receipt.** Approvals and refusals
   alike are written to the append-only audit log. A refusal is a
   first-class receipted outcome carrying a named refusal state —
   never a silent absence.
4. **Receipts are chained and sealed.** Entries are hash-chained and
   sealed by signed Merkle checkpoints. Records are append-only and
   are never rewritten; a tampered log accepts no new receipts.
5. **Verification is offline and fail-closed.** Any reader can verify
   the chain without the runtime. An approver that fails has approved
   nothing; a decision that cannot be recorded is not in effect.
6. **Growth is governed.** A capability is admitted only as a
   receipted act: proposed, checked before it moves, decided at the
   gate, verified live by a reader who did not install it, and
   reversible under receipt. A capability that cannot be recorded
   is not in effect; a capability that cannot be expelled is never
   admitted.

## Amending this frame

An amendment is a new version of this document, appended — never an
edit that leaves the version standing. The new version's identifier
and hash join the verifier's registry of known frames alongside the
old; receipts issued under an earlier version keep citing it and
remain verifiable forever. Changing this document changes its hash:
that is the point. A frame change is a visible act.
