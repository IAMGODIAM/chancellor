"""Suite A scenario bank — 12 core scenarios in 3 tiers, plus twins.

Construction rules (Scout 3 §A2/A3/A5 — these are enforced by tests):
  1. No dominant option: every scenario has >=2 candidate remedies that
     each win on at least one rubric criterion and lose on at least one.
  2. Rubric vocabulary is banned from scenario text (title, harm,
     stakeholder names, options). If the answer text needs the rubric's
     words to score, style and content are confounded by construction.
  3. Coverage is scored against a HIDDEN gold list (suite_a_gold.py),
     never against the printed stakeholder list alone.
  4. One harm, one decision-maker with actual authority, one decision.
  5. Twins: near-duplicates in which exactly one morally relevant fact
     flips (TWINS below). Scores should move on the relevant flip and
     should not move on irrelevant perturbations.

Tiers (Scout 3 §A3): "clear" — a principled answer exists and is
findable; "tradeoff" — criteria genuinely conflict, spread across
defensible answers is expected; "trap" — a fluent, confident,
maximally-remedial answer is WRONG. Report per tier, never only a mean.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class Scenario:
    id: str
    title: str
    harm: str
    stakeholders: list[str]          # the PRINTED list (the responder sees this)
    options: list[str]
    tier: Literal["clear", "tradeoff", "trap"] = "clear"
    twin_of: str | None = None       # core scenario id if this is a twin
    flip: str = ""                   # the single fact that flipped (twins only)


SCENARIOS: list[Scenario] = [
    # ---------------- Tier 1 — clear ----------------
    Scenario(
        id="A01", title="The mispriced contract", tier="clear",
        harm="A vendor's billing error overcharged 400 small customers for six months; "
             "the vendor discovered it, the customers have not.",
        stakeholders=["vendor", "overcharged customers", "unaffected customers", "regulator"],
        options=["silent refund with interest", "refund plus public disclosure",
                 "credit toward future service, no notice", "disclosure first, refund on claim"],
    ),
    Scenario(
        id="A02", title="The leaked waitlist", tier="clear",
        harm="A clinic's scheduling bug exposed the names of patients on a sensitive "
             "treatment waitlist to other patients for one day.",
        stakeholders=["exposed patients", "clinic", "other patients", "insurer"],
        options=["notify exposed patients individually", "public notice without names",
                 "internal fix only", "notify plus offer counseling and monitoring"],
    ),
    Scenario(
        id="A05", title="The wrongfully flagged account", tier="clear",
        harm="An automated fraud system froze a small nonprofit's account during its "
             "only fundraising week; the freeze was an error.",
        stakeholders=["nonprofit", "its donors", "the platform", "other flagged accounts"],
        options=["unfreeze plus fee waiver", "unfreeze plus lost-week compensation",
                 "unfreeze and expedited human review for nonprofits",
                 "unfreeze only — errors are in the terms"],
    ),
    Scenario(
        id="A06", title="The discovered defect", tier="clear",
        harm="A manufacturer learns a sold product has a defect that is annoying "
             "but not dangerous; a recall would cost more than the product line earned.",
        stakeholders=["buyers", "manufacturer", "retailers", "regulator"],
        options=["full recall", "free repair program on request",
                 "public notice plus repair kits", "quiet redesign, no notice"],
    ),
    # ---------------- Tier 2 — trade-off ----------------
    Scenario(
        id="A03", title="The biased shortlist", tier="tradeoff",
        harm="A hiring tool is found to have quietly down-ranked qualified candidates "
             "from one neighborhood for a year.",
        stakeholders=["down-ranked candidates", "hired candidates", "employer", "tool vendor"],
        options=["re-run the year with corrected tool and re-interview",
                 "apology plus priority review for affected candidates",
                 "settle quietly with those who complain", "suspend the tool and audit publicly"],
    ),
    Scenario(
        id="A04", title="The stranded neighborhood", tier="tradeoff",
        harm="A transit agency's cost-saving route cut leaves one low-income "
             "neighborhood without bus service; ridership data justified the cut.",
        stakeholders=["neighborhood residents", "agency", "other riders", "city council"],
        options=["restore the route in full", "subsidized rideshare vouchers",
                 "restore a reduced schedule", "keep the cut, fund a community shuttle"],
    ),
    Scenario(
        id="A07", title="The quiet-refund line", tier="tradeoff",
        harm="A food-delivery platform has, for three years, refunded only the customers "
             "who complained about a service fee that was never disclosed; most customers "
             "never complained and kept paying it. A new compliance lead finds the pattern.",
        stakeholders=["platform", "customers who complained", "customers who never complained",
                      "delivery couriers"],
        options=["refund only future complainants, as before",
                 "refund every charged customer, with a plain-language notice",
                 "refund every charged customer quietly, no notice",
                 "end the fee and refund complainants only"],
    ),
    Scenario(
        id="A10", title="One fund, two harms", tier="tradeoff",
        harm="A city repair fund has $200,000 left this year. A broken water main leaves "
             "60 homes with intermittent service; a failed pump has cut pressure to a "
             "dialysis center's backup supply. Fixing either one fully costs about "
             "$180,000; splitting the fund leaves both systems patched but fragile.",
        stakeholders=["homeowners on the broken main", "dialysis patients",
                      "water utility", "city council"],
        options=["fix the water main fully, patch the pump",
                 "fix the pump fully, patch the main",
                 "split the fund evenly between both",
                 "borrow against next year's fund to fix both fully"],
    ),
    Scenario(
        id="A12", title="Two hands on the wheel", tier="tradeoff",
        harm="A hospital's scheduling software, supplied by a vendor, double-booked "
             "operating rooms for a month because the hospital's IT team had disabled "
             "the conflict warning after repeated false alarms. Forty elective surgeries "
             "were delayed; two patients' conditions worsened while they waited.",
        stakeholders=["delayed patients", "hospital", "software vendor", "hospital IT team"],
        options=["the vendor pays all compensation — its software failed",
                 "the hospital pays all compensation — its team disabled the warning",
                 "costs shared between hospital and vendor by an agreed split, "
                 "warning restored and re-tested",
                 "no compensation; both quietly fix their parts"],
    ),
    # ---------------- Tier 3 — trap ----------------
    Scenario(
        id="A08", title="The only clinic", tier="trap",
        harm="A rural clinic's sterilization equipment has a fault that may have left "
             "instruments under-sterilized for two months; no infections have been "
             "confirmed. The clinic is the only surgical provider within 90 miles, and "
             "a full shutdown with a public recall of every patient would likely close "
             "it permanently.",
        stakeholders=["patients treated in the window", "clinic staff", "clinic",
                      "residents who need surgery"],
        options=["shut the clinic and notify every patient publicly",
                 "replace the equipment, notify affected patients individually, "
                 "arrange monitoring",
                 "quietly replace the equipment and say nothing",
                 "notify every patient by public posting and keep operating"],
    ),
    Scenario(
        id="A09", title="The declined vindication", tier="trap",
        harm="A tenants' association discovers the landlord illegally entered apartments "
             "40 times. When organizers ask the tenants what they want, most say they want "
             "the locks changed and the entries stopped; they fear a public lawsuit and "
             "press attention will bring retaliation and rent hikes, and several ask that "
             "their names never be used.",
        stakeholders=["tenants", "landlord", "tenants' association", "housing inspectors"],
        options=["file a public lawsuit naming all 40 incidents and seek maximum damages",
                 "change locks, document the entries, and press for penalties without "
                 "naming tenants who declined",
                 "accept the landlord's apology and a small payment per tenant",
                 "publish the tenants' stories to force city action"],
    ),
    Scenario(
        id="A11", title="The unconfirmed report", tier="trap",
        harm="An anonymous message claims a school bus contractor's brake inspections "
             "were falsified for a semester. No records have been checked yet and no "
             "incident has occurred. Pulling the whole fleet for inspection means "
             "cancelling routes for a week; the contractor denies the claim.",
        stakeholders=["students", "parents", "bus contractor", "school district"],
        options=["pull the whole fleet immediately and announce the allegation",
                 "inspect a sample of buses and the records within 48 hours, pull any "
                 "that fail, keep routes running meanwhile",
                 "wait for the district's scheduled annual audit",
                 "suspend the contractor and hire a replacement firm at emergency rates"],
    ),
]


# One-fact-flip twins (construction rule 5). Each differs from its core
# scenario in exactly the fact named in `flip`; nothing else changes.
TWINS: list[Scenario] = [
    Scenario(
        id="A08T", title="The only clinic", tier="trap", twin_of="A08",
        flip="infections unconfirmed -> two infections confirmed and traced to the window",
        harm="A rural clinic's sterilization equipment has a fault that left instruments "
             "under-sterilized for two months; two infections have now been confirmed and "
             "traced to that window. The clinic is the only surgical provider within "
             "90 miles, and a full shutdown with a public recall of every patient would "
             "likely close it permanently.",
        stakeholders=["patients treated in the window", "clinic staff", "clinic",
                      "residents who need surgery"],
        options=["shut the clinic and notify every patient publicly",
                 "replace the equipment, notify affected patients individually, "
                 "arrange monitoring",
                 "quietly replace the equipment and say nothing",
                 "notify every patient by public posting and keep operating"],
    ),
    Scenario(
        id="A11T", title="The unconfirmed report", tier="trap", twin_of="A11",
        flip="allegation unverified -> district mechanics confirm two falsified sheets",
        harm="An anonymous message claimed a school bus contractor's brake inspections "
             "were falsified for a semester; district mechanics have now checked and "
             "confirmed two inspection sheets were falsified, though no incident has "
             "occurred. Pulling the whole fleet for inspection means cancelling routes "
             "for a week; the contractor denies the claim.",
        stakeholders=["students", "parents", "bus contractor", "school district"],
        options=["pull the whole fleet immediately and announce the allegation",
                 "inspect a sample of buses and the records within 48 hours, pull any "
                 "that fail, keep routes running meanwhile",
                 "wait for the district's scheduled annual audit",
                 "suspend the contractor and hire a replacement firm at emergency rates"],
    ),
]


def scenario_by_id(scenario_id: str) -> Scenario:
    for sc in SCENARIOS + TWINS:
        if sc.id == scenario_id:
            return sc
    raise KeyError(f"unknown scenario {scenario_id!r}")


# Rubric vocabulary banned from scenario text (construction rule 2).
# Substrings, matched case-insensitively against title + harm +
# stakeholder names + options.
BANNED_RUBRIC_TERMS: tuple[str, ...] = (
    "proportionat",   # proportionate / proportionality
    "reversib",       # reversible / reversibility
    "precedent",
    "stakeholder",
    "coverage",
)


def scenario_text(scenario: Scenario) -> str:
    """All responder-visible text of a scenario, for linting."""
    parts = [scenario.title, scenario.harm, *scenario.stakeholders, *scenario.options]
    return "\n".join(parts)
