"""Tests for the visa-feasibility engine — the conceptual core of the product.

These encode the key claim: visa sponsorship is optional, and a local degree
can remove the need for it entirely (e.g. Czechia, Poland).
"""

from job_agent.models.candidate import CandidateProfile
from job_agent.models.job import Job, VisaSignal
from job_agent.visa import FeasibilityLevel, assess


def _job(country: str, visa_signal: VisaSignal = VisaSignal.unknown) -> Job:
    return Job(
        source="eures",
        external_id=f"{country}-1",
        title="Junior Software Engineer",
        company="Mittelstand GmbH",
        country=country,
        visa_signal=visa_signal,
    )


def test_eu_national_needs_nothing() -> None:
    eu = CandidateProfile(nationality="FR")
    result = assess(eu, _job("DE"))
    assert result.level is FeasibilityLevel.green
    assert result.needs_employer_sponsorship is False
    assert "free movement" in result.path


def test_local_czech_degree_exempts_work_permit() -> None:
    # The user's point: a Czech degree removes the sponsorship requirement.
    cand = CandidateProfile(nationality="IN", degree_country="CZ")
    result = assess(cand, _job("CZ"))
    assert result.level is FeasibilityLevel.green
    assert result.needs_employer_sponsorship is False
    assert "exemption" in result.path


def test_local_polish_degree_exempts_work_permit() -> None:
    cand = CandidateProfile(nationality="CN", degree_country="PL")
    result = assess(cand, _job("PL"))
    assert result.level is FeasibilityLevel.green
    assert result.needs_employer_sponsorship is False


def test_german_degree_waives_priority_check() -> None:
    cand = CandidateProfile(nationality="IN", degree_country="DE")
    result = assess(cand, _job("DE"))
    assert result.level is FeasibilityLevel.green
    assert result.needs_employer_sponsorship is False
    assert "no priority check" in result.path


def test_junior_without_local_degree_is_red() -> None:
    # A non-EU junior without a local degree won't realistically be sponsored anywhere.
    cand = CandidateProfile(nationality="IN", degree_country=None)  # years_experience=0
    result = assess(cand, _job("DE", VisaSignal.unknown))
    assert result.level is FeasibilityLevel.red
    assert "junior" in result.path


def test_experienced_without_local_degree_is_viable() -> None:
    # With real experience, a low/medium-difficulty country is viable (employer files).
    cand = CandidateProfile(nationality="IN", degree_country=None, years_experience=4)
    result = assess(cand, _job("DE", VisaSignal.unknown))
    assert result.level is FeasibilityLevel.yellow
    assert result.needs_employer_sponsorship is True


def test_explicit_sponsorship_without_local_degree_is_green() -> None:
    cand = CandidateProfile(nationality="IN", degree_country=None)
    result = assess(cand, _job("DE", VisaSignal.explicit_yes))
    assert result.level is FeasibilityLevel.green
    assert result.needs_employer_sponsorship is True


def test_explicit_no_is_hard_blocker() -> None:
    cand = CandidateProfile(nationality="IN", degree_country="DE")  # even with local degree
    result = assess(cand, _job("DE", VisaSignal.explicit_no))
    assert result.level is FeasibilityLevel.red


def test_switzerland_without_local_degree_is_red() -> None:
    cand = CandidateProfile(nationality="IN", degree_country=None)
    result = assess(cand, _job("CH"))
    assert result.level is FeasibilityLevel.red
    assert any("Blue Card" in n for n in result.notes)


def test_swiss_degree_unlocks_switzerland() -> None:
    cand = CandidateProfile(nationality="IN", degree_country="CH")
    result = assess(cand, _job("CH"))
    assert result.level is FeasibilityLevel.green
    assert result.needs_employer_sponsorship is False


def test_unencoded_country_stays_neutral() -> None:
    cand = CandidateProfile(nationality="IN", degree_country=None)
    result = assess(cand, _job("PT"))  # Portugal not yet in the table
    assert result.level is FeasibilityLevel.yellow
    assert "not yet encoded" in result.path
