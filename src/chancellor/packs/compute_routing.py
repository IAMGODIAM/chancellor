"""Pack 001 — Compute Routing (SPEC §2.2), the founding pack.

Founded by: the Lambda standing authorization (2026-11-01), the
fleet-relative compute doctrine (2026-10-25), the laborious-work
ruling (2026-11-03 00:08 EST), and the Chairman's live reminder to a
session on 2026-11-03 that heavy compute belongs on Lambda — the
reminder this pack makes unnecessary.

The Lambda burn cap is a NAMED CONFIG SLOT (``lambda_burn_cap_usd``)
with NO value: the figure is the Chairman's to set (SPEC §9) and is
never invented here. Routing itself never stages for a money word —
Lambda use within his credits is pre-authorized (2026-11-01).
"""

from __future__ import annotations

_FOUNDED = (
    "Lambda standing authorization 2026-11-01; fleet-relative compute "
    "doctrine 2026-10-25; laborious-work ruling 2026-11-03; Chairman's "
    "live Lambda reminder to a session 2026-11-03"
)

PACK = {
    "name": "compute-routing",
    "version": "1.0.0",
    "founded_by": _FOUNDED,
    "config": {
        # NAMED SLOT, NO VALUE — the Chairman sets this figure
        # (SPEC §9). None means: routing proceeds under the standing
        # authorization; the cap check arms when he names a figure.
        "lambda_burn_cap_usd": None,
        "burn_cap_slot": "lambda_burn_cap_usd",
    },
    "rules": [
        {
            "id": "COMPUTE.GPU",
            "founded_by": _FOUNDED,
            "act_classes": ["compute"],
            "phase": "launch",
            "when": {"any": [{"requires_gpu": True}, {"historical_gpu": True}]},
            "action": "route:lambda-gpu",
            "receipt": "routing",
            "override": "none",
            "priority": 90,
            "measured_by": (
                "job descriptor GPU flags: declared requires_gpu, or "
                "historical_gpu derived from the receipts log for this "
                "job kind"
            ),
            "summary": "GPU work runs on Lambda GPU, never on this box",
            "terms": {
                "frozen_protocol": True,
                "self_destruct": "box-side",
                "burn_cap_slot": "lambda_burn_cap_usd",
            },
        },
        {
            "id": "COMPUTE.HEAVY",
            "founded_by": _FOUNDED,
            "act_classes": ["compute"],
            "phase": "launch",
            "when": {
                "any": [
                    {"input_bytes": {"gt": 500_000_000}},
                    {"wall_clock_class": "long-runner"},
                    {"peak_memory_bytes": {"gt_field": "box_safe_envelope_bytes"}},
                    {"peak_memory_class": "exceeds-envelope"},
                ]
            },
            "action": "route:lambda",
            "receipt": "routing",
            "override": "none",
            "priority": 80,
            "measured_by": (
                "job descriptor: input_bytes > 500 MB, or wall_clock_class "
                "= long-runner, or peak memory above the box's measured "
                "safe envelope"
            ),
            "summary": "Heavy work routes to Lambda by measurement, not memory",
            "terms": {
                "frozen_protocol": True,
                "self_destruct": "box-side",
                "burn_cap_slot": "lambda_burn_cap_usd",
            },
        },
        {
            "id": "COMPUTE.BURST-PARALLEL",
            "founded_by": _FOUNDED,
            "act_classes": ["compute"],
            "phase": "launch",
            "when": {"all": [{"shard_count": {"gte": 4}}, {"shards_heavy": True}]},
            "action": "route:lambda",
            "receipt": "routing",
            "override": "none",
            "priority": 70,
            "measured_by": (
                "job descriptor fan-out: shard_count >= 4 independent heavy shards"
            ),
            "summary": "Parallel heavy fan-out routes per-shard to Lambda",
            "terms": {
                "frozen_protocol": True,
                "self_destruct": "box-side",
                "burn_cap_slot": "lambda_burn_cap_usd",
                "per_shard_receipts": True,
            },
        },
        {
            "id": "COMPUTE.BOX-PROTECT",
            "founded_by": _FOUNDED,
            "act_classes": ["compute"],
            "phase": "running",
            "when": {"heavy_running_locally": True},
            "action": "stage:migrate-or-justify",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 100,
            "measured_by": (
                "watchdog signal heavy_running_locally — a detected "
                "running heavy job, never the job's self-report"
            ),
            "summary": (
                "A heavy job found running locally stages for a "
                "migrate-or-justify receipt; the run is checkpointed "
                "before any move (anchoring law, 2026-11-01)"
            ),
        },
        {
            "id": "COMPUTE.LIGHT",
            "founded_by": _FOUNDED,
            "act_classes": ["compute"],
            "phase": "launch",
            "when": {},
            "action": "allow:local",
            "receipt": "policy-verdict",
            "override": "none",
            "priority": 0,
            "default": True,
            "measured_by": "absence of every heavier trigger above",
            "summary": "Orchestration, verification, light reads/writes stay local",
        },
    ],
}
