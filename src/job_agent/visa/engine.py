"""Compute visa feasibility for a (candidate, job) pair.

Design principles:
- Visa sponsorship is OPTIONAL. The engine never rejects a job merely because the
  posting is silent about sponsorship; ``VisaSignal.unknown`` is the common case.
- The only ``red`` outcomes are genuine blockers: the posting explicitly excludes
  non-EU candidates, or the candidate has no realistic legal route (e.g. non-EU,
  no local degree, in a quota-bound non-EU-Blue-Card country like Switzerland).
- Holding a LOCAL degree is the strongest positive lever and can remove the need
  for employer sponsorship altogether.
"""

from dataclasses import dataclass, field
from enum import Enum

from job_agent.models.candidate import CandidateProfile, Track
from job_agent.models.job import EmploymentType, Job, VisaSignal
from job_agent.visa.rules import COUNTRY_RULES

# EU/EEA + Switzerland: free movement of workers, no permit needed.
_FREE_MOVEMENT = frozenset(
    {
        "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR",
        "HU", "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK",
        "SI", "ES", "SE", "IS", "LI", "NO", "CH",
    }
)


class FeasibilityLevel(str, Enum):
    green = "green"  # viable; no or only light employer involvement
    yellow = "yellow"  # viable but employer must actively sponsor / file
    red = "red"  # blocked or no realistic route


@dataclass
class FeasibilityResult:
    level: FeasibilityLevel
    needs_employer_sponsorship: bool
    path: str  # short human label for the legal route
    notes: list[str] = field(default_factory=list)


def _is_free_movement(nationality: str) -> bool:
    return nationality.upper() in _FREE_MOVEMENT


def assess(candidate: CandidateProfile, job: Job) -> FeasibilityResult:
    """Assess whether ``candidate`` can take ``job``, and how.

    Returns a :class:`FeasibilityResult`; pure function, no I/O.
    """
    country = job.country.upper()

    # 0. International organisations (Track B): the legal route is the org's own
    # host-country status (e.g. a Swiss "carte de légitimation"), which bypasses
    # the national work permit entirely — so the visa is NOT the barrier here.
    # The real barriers are competitiveness and entry being internship/JPO-gated.
    if job.track is Track.intl_org:
        notes = [
            "International organisation: host-country legitimation card; national "
            "work permit and labour-market test do not apply.",
            "Visa is rarely the obstacle — competition is. Junior entry is usually "
            "via internship / traineeship / JPO.",
        ]
        if job.employment_type is EmploymentType.jpo:
            notes.append("JPO normally requires sponsorship by a donor government — "
                         "non-EU students often lack this; verify eligibility.")
        return FeasibilityResult(
            level=FeasibilityLevel.green,
            needs_employer_sponsorship=False,
            path="International organisation — host-country legitimation (permit bypassed)",
            notes=notes,
        )

    # 1. EU/EEA/Swiss nationals: free movement, done.
    if _is_free_movement(candidate.nationality):
        return FeasibilityResult(
            level=FeasibilityLevel.green,
            needs_employer_sponsorship=False,
            path="EU/EEA/CH free movement",
            notes=["No work permit required."],
        )

    # 2. Posting explicitly excludes non-EU candidates: hard blocker.
    if job.visa_signal == VisaSignal.explicit_no:
        return FeasibilityResult(
            level=FeasibilityLevel.red,
            needs_employer_sponsorship=True,
            path="employer excludes non-EU applicants",
            notes=["Posting states EU citizenship / existing work permit required."],
        )

    rule = COUNTRY_RULES.get(country)
    if rule is None:
        # Country we haven't encoded yet — don't pretend to know; stay neutral.
        return FeasibilityResult(
            level=FeasibilityLevel.yellow,
            needs_employer_sponsorship=True,
            path=f"{country}: rules not yet encoded",
            notes=[f"No visa rule for {country}; verify the national route manually."],
        )

    has_local_degree = (
        candidate.degree_country is not None
        and candidate.degree_country.upper() == country
    )

    # 3. Local degree that removes the work-permit requirement entirely (CZ, PL).
    if has_local_degree and rule.local_degree_no_work_permit:
        return FeasibilityResult(
            level=FeasibilityLevel.green,
            needs_employer_sponsorship=False,
            path=f"{rule.name}: local-degree work-permit exemption",
            notes=[
                "Local degree grants free labour-market access — no employer "
                "sponsorship needed.",
                rule.notes,
            ],
        )

    # 4. Local degree that waives the priority check / facilitates the permit.
    if has_local_degree and rule.local_degree_waives_priority_check:
        return FeasibilityResult(
            level=FeasibilityLevel.green,
            needs_employer_sponsorship=False,
            path=f"{rule.name}: facilitated permit (local degree, no priority check)",
            notes=[
                "Local degree waives the labour-market priority check; employer "
                "burden is light.",
                rule.notes,
            ],
        )

    # 5. No local degree, but the posting offers sponsorship explicitly.
    if job.visa_signal == VisaSignal.explicit_yes:
        return FeasibilityResult(
            level=FeasibilityLevel.green,
            needs_employer_sponsorship=True,
            path=f"{rule.name}: employer-offered sponsorship",
            notes=["Posting advertises visa sponsorship / relocation support.", rule.notes],
        )

    # 6. No local degree, no explicit signal: route depends on country difficulty.
    if rule.difficulty_without_local_degree == "high":
        notes = [
            f"Hard for a non-EU junior without a {rule.name} degree.",
            rule.notes,
        ]
        if not rule.blue_card_available:
            notes.append("No EU Blue Card route here.")
        return FeasibilityResult(
            level=FeasibilityLevel.red,
            needs_employer_sponsorship=True,
            path=f"{rule.name}: quota/priority-bound, no local degree",
            notes=notes,
        )

    # A non-EU JUNIOR without a local degree is realistically unsponsorable for an
    # entry-level role in ANY country: EU Blue Card salary thresholds are out of reach
    # and employers rarely file a labour-market case for a junior. The realistic routes
    # are their local-degree country (study-to-work), a post that explicitly advertises
    # sponsorship, or an international organisation — all handled above.
    if candidate.years_experience < 2:
        return FeasibilityResult(
            level=FeasibilityLevel.red,
            needs_employer_sponsorship=True,
            path=f"{rule.name}: junior + no local degree — sponsorship unrealistic",
            notes=[
                f"A non-EU junior without a {rule.name} degree is very unlikely to be "
                "sponsored for an entry-level role here. Realistic routes: the country "
                "where you studied (study-to-work), posts that advertise sponsorship, or "
                "international organisations.",
                rule.notes,
            ],
        )

    # Experienced candidate, low/medium-difficulty country: viable but employer files.
    path = (
        f"{rule.name}: EU Blue Card / work permit (employer files)"
        if rule.blue_card_available
        else f"{rule.name}: national work permit (employer files)"
    )
    return FeasibilityResult(
        level=FeasibilityLevel.yellow,
        needs_employer_sponsorship=True,
        path=path,
        notes=[
            "Viable, but the employer must sponsor the permit; sponsorship signal "
            "is unknown — worth confirming.",
            rule.notes,
        ],
    )
