"""The founding policy packs (SPEC §2.2–2.5) as data.

Each pack module carries one ``PACK`` dict in the §2.1 schema; the
Policy Engine's loader validates every rule, and a pack that cannot
cite its founding failure or standing order is refused at load.
"""

from __future__ import annotations

from typing import Any

from ..governor_receipts import GovernorReceipts
from ..policy import Pack, load_pack
from . import compute_routing, fetch_preflight, money_staging, submission_gate

BUILTIN_PACKS: list[dict[str, Any]] = [
    compute_routing.PACK,
    fetch_preflight.PACK,
    submission_gate.PACK,
    money_staging.PACK,
]


def load_builtin_packs(receipts: GovernorReceipts | None = None) -> list[Pack]:
    return [load_pack(raw, receipts=receipts) for raw in BUILTIN_PACKS]
