"""Candidate profile — the person we are matching jobs *for*.

The visa-feasibility engine keys on this. The two fields that matter most for
legal feasibility are ``nationality`` and ``degree_country``: a non-EU national
holding a degree *from the country they want to work in* is frequently exempt
from employer sponsorship (see ``job_agent.visa``).
"""

from enum import Enum

from pydantic import BaseModel, Field


class Track(str, Enum):
    """Which labour market a job/search belongs to."""

    private = "private"  # SMEs, startups, corporates — national work authorisation
    intl_org = "intl_org"  # UN / EU / NGO — separate legal status, internships, JPO


class CandidateProfile(BaseModel):
    """Everything the agent needs to know about the job-seeker.

    ``nationality`` / ``degree_country`` use ISO-3166 alpha-2 codes (e.g. ``"IN"``,
    ``"DE"``). ``degree_country`` is the country that *granted* the candidate's
    highest relevant degree, or ``None`` if they have no European degree — this is
    the single biggest lever on visa feasibility.
    """

    nationality: str  # ISO-2; the engine treats EU/EEA/CH nationals specially
    degree_country: str | None = None  # ISO-2 of degree-granting country, or None
    field: str = ""  # free text, e.g. "computer science", "mechanical engineering"
    experience: str = ""  # free text — past internships/roles, fed to semantic matching
    skills: list[str] = Field(default_factory=list)  # for CV↔job relevance matching
    languages: list[str] = Field(default_factory=list)  # ISO-639-1, e.g. ["en", "de"]
    years_experience: float = 0.0
    salary_expectation_eur: int | None = None  # annual gross, for Blue-Card thresholds
    tracks: list[Track] = Field(default_factory=lambda: [Track.private])
