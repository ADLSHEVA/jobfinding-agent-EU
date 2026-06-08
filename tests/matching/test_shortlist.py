"""Ranking: feasibility dominates; signal + language break ties; red filtered out."""

from job_agent.models.candidate import CandidateProfile
from job_agent.models.job import Job, VisaSignal
from job_agent.matching import shortlist


def _job(country: str, ext: str, signal: VisaSignal = VisaSignal.unknown, langs=None) -> Job:
    return Job(source="s", external_id=ext, title="Junior Analyst", company="C",
               country=country, visa_signal=signal, languages_required=langs or [])


def test_red_filtered_by_default_but_kept_on_request() -> None:
    # Experienced so DE is viable (yellow); CH (high difficulty, no local degree) → red.
    cand = CandidateProfile(nationality="IN", degree_country=None, years_experience=4)
    jobs = [_job("DE", "1"), _job("CH", "2")]  # CH (no local degree) → red

    default = shortlist(cand, jobs)
    assert {r.job.external_id for r in default} == {"1"}  # CH dropped

    with_red = shortlist(cand, jobs, include_red=True)
    assert {r.job.external_id for r in with_red} == {"1", "2"}


def test_explicit_sponsorship_outranks_silent_posting() -> None:
    # Experienced so the silent DE posting is viable (yellow), not red; sponsor still wins.
    cand = CandidateProfile(nationality="IN", degree_country=None, years_experience=4)
    jobs = [_job("DE", "silent"), _job("DE", "sponsor", VisaSignal.explicit_yes)]

    ranked = shortlist(cand, jobs)
    assert ranked[0].job.external_id == "sponsor"  # higher score
    assert ranked[0].score > ranked[1].score


def test_local_degree_green_tops_yellow() -> None:
    cand = CandidateProfile(nationality="IN", degree_country="CZ")
    jobs = [_job("DE", "de-yellow"), _job("CZ", "cz-green")]  # CZ local degree → green

    ranked = shortlist(cand, jobs)
    assert ranked[0].job.external_id == "cz-green"


def test_language_mismatch_lowers_score() -> None:
    cand = CandidateProfile(nationality="FR", languages=["fr", "en"])  # EU → all green
    match = _job("DE", "ok", langs=["en"])
    miss = _job("DE", "miss", langs=["de"])

    ranked = {r.job.external_id: r.score for r in shortlist(cand, [match, miss])}
    assert ranked["ok"] > ranked["miss"]
