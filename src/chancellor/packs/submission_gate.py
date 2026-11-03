"""Pack 003 — Submission Gate (SPEC §2.4), the existing gate,
formalized as a pack.

The behavior is the shipped Chancellor gate's, unchanged: no filing,
application, or response leaves without an independent lane's PASS
receipt in the gate-receipts shelf; absence blocks fail-closed; only
the Chairman waives, by name. This pack records the gate where the
Governor reads all gates from one shelf — it changes no shipped gate
semantics in chancellor.escalation / chancellor.receipts.

The engine reads the shelf through its context's ``gate_lookup``:
given the act descriptor (which names the package), it returns the
PASS entry or None. The waiver arrives as the descriptor field
``chairman_waiver`` carrying the Chairman's name, supplied by the
approval surface that actually heard him — the receipt records the
name as an override.
"""

from __future__ import annotations

_FOUNDED = (
    "Chancellor gate on submissions, Chairman's order 2026-11-03 "
    "(CHANCELLOR-GATE-SPEC): no submission leaves without an "
    "independent lane's PASS receipt; the BES CSO white paper's "
    "false SAM claim is the founding failure it answers"
)

PACK = {
    "name": "submission-gate",
    "version": "1.0.0",
    "founded_by": _FOUNDED,
    "rules": [
        {
            "id": "SUBMIT.PASS",
            "founded_by": _FOUNDED,
            "act_classes": ["submission"],
            "when": {"gate_pass": True},
            "action": "allow",
            "receipt": "gate",
            "override": "none",
            "priority": 50,
            "measured_by": (
                "gate-receipts shelf lookup: a PASS receipt naming this "
                "package, minted by an independent lane"
            ),
            "summary": "A PASS receipt in the shelf opens the gate",
        },
        {
            "id": "SUBMIT.MISSING",
            "founded_by": _FOUNDED,
            "act_classes": ["submission"],
            "when": {},
            "action": "deny",
            "receipt": "gate",
            "override": "chairman-by-name",
            "priority": 0,
            "default": True,
            "measured_by": (
                "gate-receipts shelf lookup returns no PASS for this "
                "package — fail-closed"
            ),
            "summary": (
                "No PASS receipt, no submission. Only the Chairman "
                "waives, by name, and the waiver receipts as an override"
            ),
        },
    ],
}
