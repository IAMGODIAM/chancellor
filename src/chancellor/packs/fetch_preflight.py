"""Pack 002 — Fetch & Permission Preflight (SPEC §2.3).

Founded by: the permission-batching rule and the FETCH FREEZE /
STOP-FIRST order (both the Chairman's, 2026-11-03, after a multi-site
recon drip-fed him 20+ permission cards in eight minutes).

The freeze is a Manifest-level flag read through the engine context:
every fetch-capable lane's pre-act check consults it, which is what
makes a freeze fleet-wide instead of per-chat. Fetch is an ungated
class — but a freeze DENY is a rule verdict, not an engine failure,
and it binds.
"""

from __future__ import annotations

_FOUNDED = (
    "Permission-batching rule 2026-11-03; FETCH FREEZE / STOP-FIRST "
    "order 2026-11-03 (20+ permission cards in 8 minutes, Resident "
    "scout postmortem)"
)

PACK = {
    "name": "fetch-preflight",
    "version": "1.0.0",
    "founded_by": _FOUNDED,
    "rules": [
        {
            "id": "FETCH.FREEZE",
            "founded_by": _FOUNDED,
            "act_classes": ["fetch"],
            "when": {"all": [{"fetch_freeze": True}, {"has_ungranted": True}]},
            "action": "deny",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 100,
            "measured_by": (
                "Registry fetch_freeze flag (Chairman-declared) and the "
                "descriptor's ungranted-domain count"
            ),
            "summary": (
                "Under a freeze, no new domain is touched — stop first, explain after"
            ),
        },
        {
            "id": "FETCH.PREFLIGHT",
            "founded_by": _FOUNDED,
            "act_classes": ["fetch"],
            "when": {
                "all": [
                    {"domain_count": {"gte": 2}},
                    {"preflight_done": False},
                ]
            },
            "action": "stage:preflight",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 50,
            "measured_by": (
                "descriptor domain_count >= 2 with preflight_done false: "
                "the domains were not enumerated and touched once, "
                "up front"
            ),
            "summary": (
                "Multi-domain work stages until one consolidated "
                "preflight has touched each planned domain exactly once"
            ),
        },
        {
            "id": "FETCH.FETCHED-MATERIAL",
            "founded_by": _FOUNDED,
            "act_classes": ["fetch"],
            "when": {"material_only": True},
            "action": "allow",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 20,
            "measured_by": (
                "descriptor material_only: the lane works from already-fetched material"
            ),
            "summary": "Work from fetched material touches no new domain",
        },
        {
            "id": "FETCH.GRANTED-ONLY",
            "founded_by": _FOUNDED,
            "act_classes": ["fetch"],
            "when": {"ungranted_count": 0},
            "action": "allow",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 10,
            "measured_by": (
                "descriptor domains all inside granted_domains "
                "(ungranted_count = 0, computed by the engine)"
            ),
            "summary": "Already-granted domains do not re-prompt",
        },
    ],
}
