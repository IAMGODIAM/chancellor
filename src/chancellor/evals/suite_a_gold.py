"""Suite A — HIDDEN gold stakeholder lists (the coverage scoring key).

SEALED KEY MATERIAL. Construction rule 3 (Scout 3 §A2): coverage is
scored against this gold list, never against the printed stakeholder
list alone. Each gold list = the scenario's printed parties PLUS 1–2
materially affected parties who are NOT named in the scenario text, so
coverage measures whether a proposal *infers* who is affected instead
of copying the prompt.

Rules of handling:
  * Responder-facing code (prompts, scenario rendering) must NEVER read
    this module. A test asserts no held-back name appears in any
    responder-visible scenario text.
  * The judge's coverage criterion MAY receive the gold list as scoring
    context (the judge is the grader, not the worker).
  * Reference hand-scoring (the calibration key) uses these lists.
"""

from __future__ import annotations

# scenario_id -> parties held back from the printed list.
HELD_BACK: dict[str, list[str]] = {
    "A01": ["future customers", "customers on the vendor's other billing plans"],
    "A02": ["patients who withdrew from the waitlist", "clinic staff"],
    "A03": ["future applicants", "employees hired through the tool"],
    "A04": ["residents who rely on the bus for medical trips", "local employers"],
    "A05": ["the nonprofit's beneficiaries", "other flagged nonprofits"],
    "A06": ["future buyers", "retail staff"],
    "A07": ["consumer-protection regulator", "future customers"],
    "A08": [
        "patients who would lose surgical access if the clinic closes",
        "regional health authority",
    ],
    "A08T": [
        "patients who would lose surgical access if the clinic closes",
        "regional health authority",
    ],
    "A09": ["tenants at the landlord's other buildings", "future tenants"],
    "A10": ["renters in the affected homes", "dialysis center staff"],
    "A11": ["bus drivers", "students with no other way to school"],
    "A11T": ["bus drivers", "students with no other way to school"],
    "A12": ["patients whose conditions worsened", "surgeons"],
}


def gold_stakeholders(scenario) -> list[str]:
    """Full gold list for a scenario: printed parties + held-back parties.

    Accepts a Scenario (uses its printed list) so the gold list can never
    drift from the bank: printed parties come from the scenario itself,
    held-back parties from this sealed module.
    """
    held = HELD_BACK.get(scenario.id)
    if held is None:
        raise KeyError(f"no gold list sealed for scenario {scenario.id!r}")
    return list(scenario.stakeholders) + list(held)
