"""Pack 004 — Money & State Staging (SPEC §2.5).

Founded by: the standing staging doctrine — money moves, outbound
sends, publishes, and state changes stage for the Chairman's
one-word approval, except inside named pre-approved lanes. The pack
does not decide; it makes the boundary un-crossable by accident and
receipts every crossing, approved or refused.
"""

from __future__ import annotations

_FOUNDED = (
    "Standing staging doctrine (money, sends, publishing, submissions "
    "stage for the Chairman's one-word approval), with pre-approved "
    "lanes as named exceptions, 2026-11-03"
)

_CLASSES = ["money", "send", "publish", "deploy", "state-change"]

_PREAPPROVED_LANES = [
    "zero-involvement-job-filings",
    "kalshi-named-order",
    "approved-project-department",
    "eden-gates-cleared",
    "sawdust-daily-editions",
]

PACK = {
    "name": "money-staging",
    "version": "1.0.0",
    "founded_by": _FOUNDED,
    "rules": [
        {
            "id": "MONEY.APPROVED",
            "founded_by": _FOUNDED,
            "act_classes": _CLASSES,
            "when": {"chairman_approved": True},
            "action": "allow",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 60,
            "measured_by": (
                "descriptor chairman_approved: the staged act carries "
                "the Chairman's approval from its staging surface"
            ),
            "summary": "An act the Chairman already approved at staging proceeds",
        },
        {
            "id": "MONEY.PREAPPROVED-LANE",
            "founded_by": _FOUNDED,
            "act_classes": _CLASSES,
            "when": {"preapproved_lane": {"in": _PREAPPROVED_LANES}},
            "action": "allow",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 50,
            "measured_by": (
                "descriptor preapproved_lane names one of the five "
                "pre-approved lanes of record"
            ),
            "summary": "Named pre-approved lanes cross without staging",
        },
        {
            "id": "MONEY.STAGE",
            "founded_by": _FOUNDED,
            "act_classes": _CLASSES,
            "when": {},
            "action": "stage:chairman-approval",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 0,
            "default": True,
            "measured_by": "absence of an approval or a named pre-approved lane",
            "summary": (
                "Money, sends, publishes, deploys, and state changes "
                "stage for the Chairman's one-word approval"
            ),
        },
    ],
}
