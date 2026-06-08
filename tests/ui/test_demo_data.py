"""Demo data drives the UI offline; verify it flows through the real shortlist."""

from job_agent.matching import shortlist
from job_agent.models.candidate import CandidateProfile
from job_agent.ui.demo_data import demo_jobs


def test_demo_jobs_present() -> None:
    jobs = demo_jobs()
    assert len(jobs) == 6
    assert {j.country for j in jobs} >= {"CH", "CZ", "NL", "DE"}


def test_eu_candidate_sees_all_green() -> None:
    eu = CandidateProfile(nationality="FR")  # free movement → everything viable
    ranked = shortlist(eu, demo_jobs())
    assert len(ranked) == 6


def test_non_eu_without_local_degree_filters_red() -> None:
    cand = CandidateProfile(nationality="CN", degree_country=None)
    ids = {r.job.external_id for r in shortlist(cand, demo_jobs())}
    # A non-EU junior without a local degree is only realistically viable where the
    # employer advertises sponsorship (pa) or via an international organisation (who).
    # Everything else — cz/nl/dev/de — is red (sponsorship unrealistic / blocked).
    assert ids == {"pa", "who"}
