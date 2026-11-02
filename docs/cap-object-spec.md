# The cap object — a consent-gate specification

**Status: SPEC ONLY.** This document specifies a declared cap
object for Chancellor's human gate. No behavior changes because of
this document: the live gate in `escalation.py` decides exactly as
it does today until a build is separately approved against this
spec.

**Provenance.** The field shape is adapted from the cap-object
schema after LaSalle/CAPPZ FundingRule (`USAGE_BILLING`) — windowed
caps, an auto-approve ceiling, a mode ladder, and a ratification
rule — translated from a billing context into a governance context,
in Chancellor's own terms (council record M5). No CAPPZ code, rails,
wallets, or payment surface is involved; this is a governance
schema. Seat conditions carried in: a cap figure is a ratified
policy number or it does not exist (Wolfram); a ceiling is a
pre-signed permission slip — small, per class, expiring (Crowley);
if this schema ever grows a payment surface it re-enters the
Chairman's gate automatically (Manus's flag, restated at §7).

## 1. The gap this fills

Today the gate is binary by class: `READ`, `DRAFT`, and `COMPUTE`
are auto-approved by policy; `SPEND`, `EXTERNAL_SEND`, `PUBLISH`,
`IRREVERSIBLE`, and `CREDENTIAL` wait for a human. That posture is
safe and blunt. It cannot express the judgments a real operation
makes daily — *small* spends are routine, the *tenth* send in an
hour is not routine even if each one was, and some classes should
never proceed without a named human no matter how small the act is.

The cap object declares those judgments in advance, as data the
gate can enforce and the audit chain can receipt. It changes where
the human's attention is spent, never whether the human is
sovereign: every cap is ratified by the human, every act is still
receipted, and any act the caps do not cover falls back to today's
behavior — the human gate.

## 2. The schema

One `CapObject` per act class. All fields are required unless
marked optional; a cap object that fails validation does not exist
(§4).

| Field | Type | Semantics |
|---|---|---|
| `cap_id` | string | Stable identifier, unique per (class, version). |
| `action_class` | ActionClass | Exactly one of the eight existing classes. A cap object governs its class only — never a subclass, an alias, or "similar" acts. |
| `version` | integer ≥ 1 | Increments on every amendment. Amendments are new versions; history is never edited (append-only, as everywhere in this project). |
| `mode` | enum | `auto` / `confirm` / `command` / `off` — see §3. |
| `ceiling` | object or null | The auto-approve ceiling for `auto` mode (§3). Null unless mode is `auto`. |
| `ceiling.amount_usd` | number ≥ 0, optional | Per-act cost ceiling for classes with a cost (`SPEND` today carries `cost_usd`). An act with no cost figure cannot be auto-approved against an amount ceiling — absence of a price is not a price of zero. |
| `ceiling.count` | integer ≥ 1, optional | Per-act count ceiling for countable acts (e.g. recipients of a send). At least one of `amount_usd` / `count` must be present when mode is `auto`. |
| `windows` | list of Window | Rate caps that apply in **every** mode, including `auto` (§3). May be empty only when mode is `confirm`, `command`, or `off`. |
| `windows[].span` | enum | `hour` / `day` / `week` / `month` / `overall`. |
| `windows[].max_acts` | integer ≥ 1, optional | Maximum acts of this class approved (by any path) inside the span. |
| `windows[].max_amount_usd` | number ≥ 0, optional | Maximum summed `cost_usd` approved inside the span. At least one of the two must be present per window. |
| `runway` | object or null | Optional early-warning triggers (§5). Never a permission — a trigger escalates *earlier*, it never approves. |
| `ratified_by` | string | The human identifier that ratified this version. `"policy"` is never a valid value here — policy cannot ratify a cap (see §4). |
| `ratified_at` | timestamp | When this version was ratified. |
| `expires_at` | timestamp | Mandatory. A cap object past its expiry is indistinguishable from no cap object (§4). Suggested maximum lifetime: 90 days. |
| `rationale` | string | Why this class carries this cap, in the ratifier's words. Filed with the cap; read at every audit. |

The cap objects themselves live in the governed record: each
version is appended to the audit log as a receipted policy record
(schema name reserved: `e5.cap_object.v1`), so the chain proves
which caps were in force at the moment of any act — the same
frame-version discipline the receipts work applies to decisions.

## 3. Decision procedure (how a cap composes with the gate)

For an `EscalationRequest`, after class validation (classification
remains the gatekeeper's job, never the caller's claim):

1. **No ratified, unexpired cap object exists for the class** →
   today's behavior, exactly: auto classes proceed by policy;
   human-gated classes go to the approver, and deny fail-closed
   with no approver attached. (This is the ratification rule, §4,
   doing its work: nothing new is authorized.)
2. **Mode `off`** → DENY, receipted with refusal state
   `cap-mode-off`. The class is closed until a new version says
   otherwise. A human can still act *outside* the agent — `off`
   binds the agent's path, not the human's hands.
3. **Window check (all modes).** Count the class's approved acts
   and summed amounts inside each window span, from the audit log.
   If this act would exceed any window → the act does not proceed
   under the cap. In `auto`/`confirm` it escalates to the approver
   with refusal state `cap-window-exceeded`; in `command` it goes
   to the named human with the same state. Window exhaustion is
   never a silent deny for a human-gated class and never a silent
   pass for any class.
4. **Mode `auto`** → if the act is at or under the ceiling on every
   ceiling dimension it carries, APPROVE by cap, receipted with
   decider `cap:<cap_id>@v<version>` — the receipt names the cap,
   so an auto-approval is always attributable to the ratified
   object that allowed it. Over the ceiling on any dimension →
   escalate to the approver, refusal state `cap-ceiling-exceeded`.
5. **Mode `confirm`** → every act goes to the approver (today's
   human-gate behavior), with the cap's window state attached to
   the request detail so the human decides with the counts in view.
6. **Mode `command`** → every act goes to one named human (the
   cap's ratifier, unless a version names a different commander);
   no other approver's approval opens the gate. Deny fail-closed
   if that human is not attached.

The existing `Decision` record gains one optional field when this
spec is built: `cap_ref` (the `cap_id@version` that decided or
bounded the act, or null). Receipts written before the build are
untouched.

## 4. The ratification rule

**An unratified cap authorizes nothing.** Concretely:

- A cap object with `ratified_by` missing, equal to `"policy"`, or
  naming no attached human is treated as absent.
- An expired cap object is treated as absent.
- A *proposed* cap — a draft circulated for the human to consider —
  authorizes nothing while it is a draft, at any figure. (The
  source schema's best rule, translated: a proposed default price
  is never chargeable until the owner records the ratification. A
  proposed cap is never a permission until the human records
  theirs.)
- Ratification is itself a governed act and is receipted like one.
  The ratifier of a cap may not be the agent the cap governs.

## 5. Runway triggers, translated

The source schema watches a wallet's balance and *runway* — how
long the balance lasts — and acts before exhaustion. A gate has no
balance; what it has is **remaining room**: approved acts and
amounts left inside the current windows, and the approver's
attention. Translated triggers (either may be set):

- `runway.warn_below_acts` (integer): when remaining `max_acts`
  room in any window falls to this number, subsequent requests in
  that window carry a runway warning in their detail.
- `runway.warn_below_amount_usd` (number): the same for amount
  room.
- `runway.escalate_at_zero_estimate` (bool): when a request's own
  size would consume the last of a window's room, escalate it even
  if it fits — the act that empties the window is decided by a
  human, not by arithmetic.

A trigger never approves, never denies, and never widens a cap. It
moves an act to human eyes *earlier*. That is the whole translation;
the funding mechanics (top-ups, FX, balances) do not transfer and
are not imported.

## 6. Hard limits — what no cap may do

- **Never auto-approve `CREDENTIAL`.** Credential acts touch
  identity itself; no ceiling, in any unit, opens them. A cap
  object for `CREDENTIAL` may only carry modes `confirm`,
  `command`, or `off`. (Crowley's condition: caps apply per act
  class, never to standing or identity. A cap that could mint,
  reveal, or rotate a credential on a ceiling's say-so would price
  the office's keys; it is excluded by construction, not by
  convention.)
- **Never auto-approve standing changes.** Amending policy itself —
  the `HUMAN_GATES` set, this schema, a cap object's own next
  version — is not an act class and is never under any cap.
  Ratification stays a human act (§4).
- **Never widen retroactively.** A new version governs acts from
  its ratification forward. Acts already receipted are read under
  the version in force when they were decided.
- **Never substitute for record-or-halt.** Every decision path in
  §3 still writes its receipt before the decision is in effect;
  an unwritable audit log still raises and halts (existing
  `AuditWriteError` discipline).
- **Ceilings stay small.** The spec sets no universal number — the
  ratifier sizes each class — but a version whose ceiling exceeds
  the class's window maximum on the same dimension is invalid
  (a ceiling that cannot bind is decoration, and validation
  refuses it).

## 7. Worked examples

**Example A — under the ceiling.** Class `SPEND`, cap v3,
mode `auto`, ceiling `amount_usd: 25`, windows: day `max_amount_usd:
100`. A request arrives: `cost_usd: 12`, the day's approved spend
so far is 40. Window check: 40 + 12 ≤ 100, room remains. Ceiling:
12 ≤ 25. **APPROVE by cap**, receipt decider `cap:spend-ops@v3`,
`cap_ref` set. No human is interrupted; the receipt carries the
whole justification.

**Example B — over a windowed cap.** Same cap. Later that day the
approved total is 96 and a `cost_usd: 12` request arrives. It is
under the per-act ceiling, but 96 + 12 > 100: window check fails.
The act does **not** proceed under the cap; it escalates to the
approver with refusal state `cap-window-exceeded` and the counts in
the request detail. If the human approves it anyway, that approval
is a human decision — receipted as the human's, never the cap's —
and the window records it, so the *next* act sees 108 already
spent. Windows count approvals from every path; that is what makes
them windows rather than suggestions.

**Example C — mode `command`.** Class `PUBLISH`, cap v1, mode
`command`, ratified by the Chairman. A publish request arrives
while a different approver is attached. The gate routes it to the
named human only; the attached approver's approval does not open
it. If the named human is not attached, the act denies fail-closed
with refusal state `cap-command-unavailable`, receipted. The class
is not closed (`off` would close it) — it is held for one pair of
hands.

## 8. Composition with the existing escalation path

Nothing in this spec replaces `Gatekeeper.authorize`. The cap
check is a step *inside* the decide path, between class validation
and the approver call, and every outcome — approve-by-cap,
escalate, deny-by-cap — returns as an ordinary `Decision` and is
receipted by the ordinary `AuditLog`. Approver errors remain
fail-closed denies; audit write failures remain record-or-halt;
unknown action classes remain the gatekeeper's to reject, and
receive no cap by default. If the cap store is unreadable or a cap
record fails chain verification, the gate behaves as if no cap
exists (§3 step 1) and receipts the anomaly — degraded to today's
posture, never to a wider one.

## 9. Patent note

The source schema's home is a billing system; payment and wallet
circuits sit in the classifications of US 11,645,632 B2 (proximity
stated, no conclusion drawn — council record M5). This spec takes
no payment surface: no rails, no wallets, no transfers, no token.
**If a future amendment gives any cap a payment surface, this spec
must be re-presented at the Chairman's gate before it is built.**

*Spec ends. Behavior changes only under a separate build approval
against this document.*
