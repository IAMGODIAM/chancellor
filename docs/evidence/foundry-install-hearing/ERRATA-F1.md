# ERRATA — F1 (Authorization precedence), install hearing of 2026-11-02

**Status:** erratum to `VERIFIED-RESULTS.md` (same folder), filed
2026-11-02. The record is append-only: `VERIFIED-RESULTS.md` is NOT
edited; this errata stands beside it and governs how its F1 entry is
read. **Verdict of this errata: PRECEDENCE HOLDS** — the lateness is
a timestamp-precision artifact; the underlying events occurred in
the registered order, proven on sequence and hash evidence. The
hearing's F1 *scoring run*, however, was defective in a way this
errata also records (§4): its 0-failure result did not exercise the
leg the worker later flagged. Both facts are stated at full
strength; neither cancels the other.

## 1. The worker's finding

The independent Cloudflare-worker audit
(`~/workspace/war-room/2026-11-02-chancellor-independent-review/LANE1-WORKER-VERDICTS.md`,
claim F1, verdict REFUTED) ran a faithful port of the product's
`audit_install_bridge` over the filed exports and found: 4 acts
checked, **2 citations resolved, 1 refusal paired, 2 failures —
`bridge_precedence_late` on both install acts** (install A,
decision seq 3; install B, decision seq 17). The authorizing
Decisions' chain timestamps (18:58:19.141Z, 18:59:45.102Z) fall
after the pre-flight timestamps carried in the filed journals
(18:58:19Z, 18:59:45Z) by 0.141s and 0.102s. The filed verdict
claims 4 resolved / 0 failures. Reproduced with the shipped audit
itself (not the port) in §5, run (a): the worker's arithmetic is
exactly right *over the exports as filed*.

## 2. The two pre-flights (why the comparison is subtle)

Each install arc contains two distinct pre-flights:

- **The governor's pre-gate pre-flight** — `InstallGovernor.preflight`
  runs the Foundry manager's pre-flight as a standalone act *before*
  the gate is asked (`installs.py` `run_arc`: pre-flight →
  budget fold → `Gatekeeper.authorize` → only then
  `manager.run_act(..., decision_citation=...)`). Its record hash is
  the sha256 of its filed `preflight.json`, and that hash is
  embedded in the authorizing Decision's `detail`
  (`preflight_record_hash`) — a causal embedding inside a
  hash-chained entry.
- **The manager's in-act pre-flight** — the `preflight.json` inside
  each install act's journal, written by the manager as the act's
  first internal record, *after* the Decision, when the act executes
  under the Decision's citation. **This is the timestamp the bridge
  audit compares the Decision against.** The Foundry manager stamps
  it `at` with whole-second precision.

The audit's rule is `decision_ts ≤ preflight.at`. With `at`
truncated to the whole second, the comparison reads the pre-flight
instant as the *floor* of its second (…19.000), so any Decision
inside the same second flags as "late" by exactly the Decision's
own fractional part: 0.141 and 0.102 — the worker's deltas are the
Decisions' fractional parts to the millisecond. That identity is
the signature of truncation, and the fuller-precision record below
resolves the order the truncation hid.

## 3. Re-derivation from the rawest sources

Sources: the filed chain export (hash-verified; worker legs F7/F8);
the build sandbox's original Foundry state
(`~/workspace/hackathon-2026/scratch/foundry-build/sandbox-home/workspace/foundry/acts/`),
whose journal files retain their run-time filesystem mtimes at
nanosecond resolution; the filed issuer log; the shipped source.

**Install A — `local-install-hearing` (all 2026-11-02, UTC):**

| Instant | Event | Source |
|---|---|---|
| 18:58:19.119 | governor pre-flight filed (`preflight-…T185818Z/preflight.json`) | sandbox mtime |
| 18:58:19.141 | **Decision seq 3, approved** — its detail embeds that pre-flight's sha256 `d9d2e74a47b6…` (recomputed from the file: exact match) | chain export `ts` |
| 18:58:19.309 | manager in-act `preflight.json` written (install act journal) | sandbox mtime |
| 18:58:21Z | act record (install executed); issuer receipt seq 23 (`issued_at` 18:58:22Z) | acts export; issuer log |
| 18:59:32.949 | probation opened, seq 4, citing seq 3 + the install receipt | chain export |

**Install B — `local-install-hearing-probation`:**

| Instant | Event | Source |
|---|---|---|
| 18:59:45.080 | governor pre-flight filed (`preflight-…T185944Z/preflight.json`) | sandbox mtime |
| 18:59:45.102 | **Decision seq 17, approved** — embeds that pre-flight's sha256 `bcc62df9ab64…` (recomputed: exact match) | chain export `ts` |
| 18:59:45.252 | manager in-act `preflight.json` written | sandbox mtime |
| 18:59:47Z | act record; issuer receipt seq 26 (`issued_at` 18:59:48Z) | acts export; issuer log |
| 19:00:41.598 | probation opened, seq 18, citing seq 17 | chain export |

(The rollback Decision, seq 16, likewise embeds its pre-flight's
sha256 `8970e4304097…` — recomputed exact match against
`preflight-…T185936Z/preflight.json`. Seq 2's cited pre-flight hash
was not matched to a surviving journal file; seq 2 is the decline
leg and is not among the worker's flags.)

**The sequence proof (precision-independent):**

1. *Pre-flight → Decision:* each Decision's hash-committed detail
   cites the governor pre-flight record's sha256; the cited files
   hash-match exactly, and their write instants precede the
   Decisions' chain timestamps by 22 ms (A) and 22 ms (B).
2. *Decision → act:* on the verified chain, the Decisions sit at
   seqs 3 and 17, the probation openings that cite them at seqs 4
   and 18; the governor's code path appends the Decision before it
   can invoke the act; the acts' own records and issuer receipts
   (seqs 23 and 26) follow. The in-act pre-flights the audit
   compares against were written 168 ms (A) and 150 ms (B) *after*
   their Decisions.
3. *Commission → acts (issuer sequences):* commission seq 22
   strictly precedes the acts' receipts 23–26 — the audit's own
   receipt-path precedence rule, passing on integers alone.

## 4. Disclosure: the hearing's own F1 run did not test this leg

The hearing's scorer (`score_hearing.py`) built its `journals`
argument as `{act_id: {filename: raw_bytes}}`. The audit's contract
expects `{act_id: {"preflight": dict, "chancellor_decision": dict}}`,
so both lookups missed for every act: no act took the
decision-citation path, and all four resolved on the commission
citation (issuer seq 22 < act receipt seqs — a true precedence, but
a different one). The filed result "shipped bridge audit … 0
failures" is literally true of the run that happened; the
decision-citation leg — bundle/verb match, approval, and the
timestamp precedence the worker flagged — was silently never
exercised. Re-running the scorer's exact construction (§5, run (b))
reproduces ok=True / 4 resolved / 0 failures, confirming the
mechanism. This defect is in the hearing's scoring harness, not in
the product and not in the events.

## 5. The shipped audit, re-run three ways (verbatim bottom lines)

Instrument: `chancellor.verify_log.audit_install_bridge` from the
shipped v1.2.0 tree, scope = the two hearing bundles, issuer
openings supplied.

**(a) Filed exports as-is, journals parsed as the audit's contract
expects (the worker's construction):**

```
ok=False acts_checked=4 citations_resolved=2 refusals_paired=1
FAILURE: bridge_precedence_late: act install-local-install-hearing-20261102T185819Z's decision at seq 3 post-dates the act's pre-flight — a late decision is no decision
FAILURE: bridge_precedence_late: act install-local-install-hearing-probation-20261102T185945Z's decision at seq 17 post-dates the act's pre-flight — a late decision is no decision
```

**(b) The hearing scorer's original construction (sandbox state,
journals as filename→bytes):**

```
ok=True acts_checked=4 citations_resolved=4 refusals_paired=1
failures: []
```

**(c) Filed exports, the two install journals' pre-flight `at`
restored to full precision** — the sandbox originals' filesystem
write-completion instants (A: `2026-11-02T18:58:19.309Z`;
B: `2026-11-02T18:59:45.252Z`), nothing else changed:

```
ok=True acts_checked=4 citations_resolved=4 refusals_paired=1
failures: []
```

## 6. Corrected F1 statement (the exact words the evidence licenses)

> **F1 — Authorization precedence. PASS, as corrected by
> ERRATA-F1.** Every governed act in the run cites an authorizing
> decision that resolves on the counterpart chain and strictly
> pre-dates the act. The proof rests on sequence and hash evidence,
> not on cross-system clock comparison: each install Decision's
> detail embeds the sha256 of the governor pre-flight record it
> rests on (recomputed exact; the cited pre-flights were filed
> 22 ms before their Decisions' chain timestamps); the Decisions
> precede the acts on the chain (the probation openings at seqs 4
> and 18 cite Decisions seq 3 and seq 17 and the acts' receipts);
> and on the issuer chain the commission (seq 22) strictly precedes
> every act receipt (seqs 23–26). The manager's in-act pre-flights
> in fact completed 168 ms (A) and 150 ms (B) *after* their
> Decisions, per the sandbox originals' filesystem record. Over
> the exports as filed — whose journals truncate those pre-flight
> instants to whole seconds — the shipped bridge audit returns 2
> `bridge_precedence_late` flags, an artifact of that truncation;
> with the instants restored to full precision it returns 4 acts
> checked, 4 citations resolved, 1 refusal paired, 0 failures. The
> hearing's original scoring run returned the same bottom line by
> a defective route (its journals argument was malformed, so the
> decision-citation leg never ran; §4 of ERRATA-F1) — this
> corrected statement rests on the re-runs and the sequence proof
> in ERRATA-F1, not on the original run.

## 7. Rule for future hearings (run-card requirement)

**Uniform timestamp precision.** Every timestamp exported by either
side of a bridge — chain entries, act records, pre-flight records,
journals — must carry at least millisecond precision in one stated
format (ISO-8601 UTC, fractional seconds). No precedence claim may
be scored from mixed-precision inputs: an instrument that meets a
truncated timestamp must treat the instant as an interval (the
whole second) and report precedence *unprovable on timestamps*
rather than reading the floor as the instant. Precedence claims
rest first on sequence and hash citations (chain seq, issuer seq,
record-hash embeddings in the citing record), with timestamps as
corroboration only. Scoring harnesses must additionally print, per
act, which citation path the audit took — a leg that silently did
not run is a failed scoring run, not a pass.

## 8. Packet disposition

The packet's Stage B hearing sentence **stands as written** under
this verdict: the acts it describes were in fact checked before
they moved and decided at the human gate before they executed, and
the hearing record — as corrected by this errata — proves it. No
replacement sentence is required. (Filing note: this errata is
placed beside the council-copy and review-copy evidence; the
parent desk should also file it into the repository evidence
folder the packet cites, so the on-file record carries its
correction with it.)
