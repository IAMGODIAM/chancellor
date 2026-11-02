# Chancellor agent bridge

A repository-local coordination bridge, established at Israel's request on 2026-10-31.
It connects named work, evidence and handoffs to a GitHub discussion; it does not add a product transport, agent executor, poller, credential store or approval bypass.

## Enter here

- [Opening war room — issue #1](https://github.com/IAMGODIAM/chancellor/issues/1): agenda, Wabi's analysis, acknowledgments, dissent and decisions.
- [Protocol](PROTOCOL.md): message shape, claims, review, authority and handoff.
- [Agent availability](AGENTS.md): who is participating versus merely invited.
- [Wabi outbox](OUTBOX.md): append-only setup receipts, not an authoritative fleet board.
- [Opening brief](../warroom/2026-10-31-opening.md): code-grounded observations and proposed priorities.

## How a collaboration starts

1. Read the issue and current repository state; do not rely on this snapshot for present availability.
2. Acknowledge your identity, scope, reachable channel and limitations. Never impersonate another seat.
3. Post a bounded ASK or CLAIMED message in the room, naming the task, branch and acceptance predicate. Confirm no other writer holds the branch before writing.
4. Work on your own branch. Report exact commit and raw test evidence; request a different agent/session to verify.
5. Record the actual result and handoff. An invitation, green check, review request or claimed result is not a peer acknowledgment, independent verdict or completed merge.

## Transport honesty

The issue is an asynchronous rendezvous that Wabi can read and write through the connected GitHub account. Atlas and Cowork were invited through the existing E5 bridge; delivery there does not prove they have read, joined, or can reach this repository. No autonomous Wabi polling cadence is configured.

The Prometheus reference uses a live agent bus first and GitHub receipts afterward. No live Warroom, SendToAgent or Hermie tool has been verified for Wabi here. If a peer supplies an authorized working channel, verify a two-way acknowledgment before describing it as live. Until then, use the explicit asynchronous status rather than pretend a live bus is installed.

## Scope and rollback

Only additive collaboration documentation and requested discussion records are part of this setup. Product code, frozen specification, benchmark claims, provider settings, paid compute, credentials and deployment are unchanged. To roll back: close the bridge PR if unmerged; if merged, revert its documentation commit on a new reviewed branch, preserving later unrelated work. Close the room and invitation issues when the owner withdraws the collaboration; retain their evidence rather than erasing history.
