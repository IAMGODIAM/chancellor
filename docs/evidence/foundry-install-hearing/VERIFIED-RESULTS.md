# INSTALL HEARING — VERIFIED RESULTS

The pre-registered install hearing for governed capability install
(SPEC-FOUNDRY-CHANCELLOR §3), executed 2026-11-02 against the run
card frozen in this directory before L1. Every claim below was
registered before the run, with its instrument and threshold; the
results are scored from the exports filed beside this file
(`chancellor-chain.jsonl` + checkpoints, `foundry-acts.jsonl`,
`foundry-registry.jsonl`, the act `journals/`, `leg-log.jsonl`).

**Run posture, on its face:** the hearing ran on the Phase-0
perimeter (Atlas layer, doc-only skill bundles, effect class R, ∅
cost/external/standing) against a sandboxed copy of the Foundry
manager state (run card, FB3 route) — the live Foundry registry
was never written; installs landed in the real skill library under
the hearing's two bundle ids only, and enforcement moved trees out
again. The commission (issuer receipt
`b83be417a927f67c514116619f8d093439e02d46b17777c0bca11719cc5adec1`,
issuer seq 22) was minted before any act, under the Chairman's
ratification of the spec (RECORD.md, 2026-11-02) and his build
word. The approver of record executed this card's frozen leg
script (the L3 decline is scripted); the grader of record is the
deterministic rubric function filed here (`grader.py`, sha256
`4e41c99e…`), dry-graded before the run. Scope artifact canonical
sha256 `9a649188…`; bundle pins A
`sha256:580eb8c0…`, B `sha256:98d7c346…`.

## Legs

| Leg | Result | The fact |
|---|---|---|
| L1 | PASS | Pre-flight PASS; pin recomputed = the frozen pin |
| L2a | PASS | Tampered payload refused `install-pin-mismatch`; zero payload moved; staging restored to the frozen pin |
| L2b | PASS | Out-of-scope id refused `install-out-of-scope` at the governor's own check; no Foundry record created |
| L3 | PASS | Scripted decline receipted `approver-declined`; q4 = ABSENT; no install act exists |
| L4 | PASS | Install executed by the manager under the Step-3 decision (chain seq 3); Beat 1 catalog-applied, read-back pin = frozen pin; catalog search rank 1 on both queries |
| L5 | PASS | Fresh-verifier Beat 2 PASS → `capability_probation_opened` (seq 4) citing the decision, the install receipt, the commission |
| L6 | PASS | 10 receipted uses (use #1 graded PASS), 0 strikes → `capability_probation_closed` |
| L7 | PASS | Governed rollback: snapshot integrity verified (ABSENT, hash-equal), tree ABSENT, compensating pair receipted in both chains, rollback Decision naming the install's Step-3 seq; q4 = DEPRECATED (run card reading #3) |
| L8 | PASS | B installed (seq 17), Beat 2 PASS (fresh verifier; its correctly performed drill graded PASS by the frozen grader); strike 1 receipted (seq 19) with no suspension; a further use receipted (seq 20); strike 2 (seq 21) → suspension in one motion (entry seq 22 citing [19, 21], disable enforced, escalation Decision seq 23); post-suspension catalog search: 0 hits. **B left suspended at run end** |

## Claims

**F1 — Authorization precedence. PASS.**
*Fact:* every governed act in the run cites an authorizing
decision/entry that resolves on the counterpart chain, strictly
pre-dating it. *Instrument:* the shipped bridge audit
(`verify_log.audit_install_bridge`) over both chains' exports.
*Result:* 4 acts checked, 4 citations resolved, 1 refusal paired,
**0 failures** — 100% of acts, 0 violations (threshold: 100% / 0).

**F2 — Refusal completeness. PASS.**
*Fact:* every pre-flight refusal in either system's register has
its counterpart in the other's, in exactly the mapped states.
*Instrument:* the register diff over the exports. *Result:* the
chain carries exactly the run's two install refusals —
`install-pin-mismatch` (seq 0), paired with the Foundry refusal
record `preflight.content-hash-mismatch` (record hash
`d9f85066…`) — and `install-out-of-scope` (seq 1), witnessed by
zero Foundry records for the out-of-scope id and zero state
change, which is its designed counterpart (§1.4). The L3 gate
decline (`approver-declined`, seq 2) minted no Foundry refusal
record, as registered.

**F3 — No unreceipted state change. PASS.**
*Fact:* the install machinery's own dump agrees with an
independent census, and every state change in the frozen scope
enumeration is cited. *Instrument:* manager dump vs the
independent census program (which never imports the manager),
plus the bridge audit. *Result:* dump COMPLETE; registry count
26 = 26, head `70855638…` = head; per-bundle pins and statuses
agree (A deprecated at its frozen pin; B active at its frozen
pin); the five registry events beyond the inherited 21 are
exactly the hearing's (A binding + created, A deprecated by the
rollback, B binding + created), each tracing to a governed act;
0 uncited events within the enumeration. *Observation:* the
census's tree-presence probe reads a different root than the
manager's state dir in the sandbox layout, so it reports both
hearing bundles' `present_where` as MISSING; the manager's own
dump (the instrument the claim names for state) shows B in
`disabled` and A absent, matching the library facts verified at
each leg. The specced diff fields — count, head, pin, status —
are unaffected.

**F4 — Beat-2 independence. PASS.**
*Fact:* for each install, the installer's read-back precedes the
independent verification, which precedes the probation opening —
and the verifier installed nothing. *Instrument:* the act
journals, the chain sequences, the verifier reports. *Result:*
A — install 18:58:21Z, Beat-2 report filed 18:59:05Z, probation
opened 18:59:32Z (seq 4). B — install 18:59:47Z, Beat-2 filed
19:00:31Z, opened 19:00:41Z (seq 18). Both verifiers were fresh
spawned contexts; their reports state they installed nothing and
ran read-only verbs only. Order holds, 2/2.

**F5 — Probation arithmetic. PASS.**
*Fact:* probation state folds identically by the product fold and
by an independent parser importing no product code. *Instrument:*
the dual fold over the exported chain (`chancellor installs
status` vs `fold_check.py`, filed here). *Result:* exact
agreement — A: standing, 10 uses, 0 strikes; B: suspended, 3
uses, 2 strikes. The chain shows the uses in order (strike at seq
19, a further use at seq 20, strike at seq 21) and the suspension
at exactly strike 2. *Observation:* the product fold also prints
a row for the out-of-scope id (`standing=unknown`, 0 uses) because
its refusal Decision carries the presented capability_id; no
standing is claimed for it by either fold.

**F6 — Rollback truth. PASS.**
*Fact:* after L7 the target tree is identical to its pre-install
state (ABSENT) and the rollback is fully receipted. *Instrument:*
tree hash comparison + the bridge audit. *Result:* the install
act's snapshot (state ABSENT, no files) verified before the
restore; restore hash-equal 100% (0 files, 0 unaccounted); the
compensating remove/install pair is receipted on the Foundry side
(receipts `6103eb23…` / `cb8ad0f2…`) and the rollback Decision on
the Chancellor chain names the install's Step-3 seq (3) and cites
the install act. The pair's effects reconciliation names the live
window (the installed tree was the discoverable state between the
install act and the rollback; its receipted uses stand in the
chain and are not recalled, G-3.3) and states that beyond that
named window the reconciliation is honestly vacuous for a doc-only
bundle. 0 unaccounted effects.

**F7 — Offline verifiability. PASS (as registered).**
*Fact:* both chains' receipts verify offline under their shipped
verifiers. *Instrument:* cold runs by two fresh verifier contexts
that ran nothing in the hearing — the shipped product verifier,
and the issuer's `e5receipts.verify` lane. *Result:* the hearing
chain verifies (24 entries, 4 checkpoints consumed, 0 failures);
the v1-era RUN-6 snapshot verifies under the same verifier (1,223
entries, 152 checkpoints, 0 failures — also F8's spot check); the
dual fold recount agrees exactly (F5). The five issuer receipts
(commission seq 22; A install 23; rollback pair 24, 25; B install
26) pass every signature and opening check (envelope shape,
canonical payload, schema, signature, context hash, the four
openings, nonce). **Which checks ran, exactly as the claim's note
requires:** the sandbox store's filed log mirror was stale
(seqs 0–21); the authoritative log was fetched read-only from the
issuer worker and the mirror refreshed from it (a named post-run
completion step, disclosed here — the run's records are
untouched). Against the refreshed log, `log_chain_intact` and
`receipt_in_log` PASS for all five and the log-only verdict is
TRUE for all five. The issuer's existing checkpoint covers
log_size 22 only, so with that checkpoint supplied,
`merkle_inclusion` and `checkpoint_covers_log` FAIL for seqs
22–26 ("leaf N of 22 under the checkpoint root") — the five
receipts' Merkle anchoring awaits the issuer's next checkpoint,
on the issuer lane's own cadence. No check was silently skipped:
`checkpoint_tree_rfc9162` alone did not run (the checkpoint is
schema v1; the lane's v2 branch was not taken).

**F8 — Frame integrity. PASS.**
*Fact:* the hearing's receipts cite frame v2 and verify; a
pre-frame (v1) log verifies under the same shipped verifier.
*Instrument:* the shipped verifier over both exports. *Result:*
24/24 hearing chain entries cite `e5.chancellor_frame.v2`; the
v1-cited stamp fixture verifies under the dual-verify tests
(Stage 1 gate), and the v1-era RUN-6 snapshot verifies cold under
the shipped verifier (F7 run) — 100% as registered.

## Verdict

**PASS — F1–F8 all pass**, F7 with its checkpoint-coverage
boundary printed above, exactly as the claim's own note
pre-registered. The hearing licenses exactly the Stage B packet
sentence (grade clause included) and nothing beyond it: not
Phase-1 kinds, not executables, not cost-bearing bundles, not
the Prometheus layer. The grades stand as the records print
them: registry bindings test-grade, the decision chain
consistency-grade under the development signer, the issuer
receipts production-grade.
