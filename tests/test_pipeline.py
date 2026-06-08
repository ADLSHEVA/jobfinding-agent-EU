"""End-to-end pipeline: Scout (Track A + B) → visa enrich → candidate shortlist.

The capstone: one run turns raw multi-source jobs into a ranked, visa-aware
shortlist for a specific candidate — here the Geneva International Relations
graduate. Fully offline.
"""

from job_agent.agents import ScoutAgent, ScoutQuery
from job_agent.data.example_seeds import SWISS_SEEDS
from job_agent.discovery import DiscoveryQuery, SeedDiscoverer
from job_agent.matching import shortlist
from job_agent.models.candidate import CandidateProfile, Track
from job_agent.models.job import VisaSignal
from job_agent.sources.intl_org import ReliefWebSource
from job_agent.visa import FeasibilityLevel, VisaSignalClassifier

# Swiss public-affairs employer (Personio) + a Geneva UN role (ReliefWeb).
_PA_XML = """<?xml version="1.0"?><workzag-jobs>
  <position><id>77</id><name>Junior Public Affairs Officer</name><office>Geneva</office>
    <jobDescriptions><jobDescription><name>r</name>
      <value>International team; relocation support available.</value></jobDescription></jobDescriptions>
  </position></workzag-jobs>"""

_RELIEFWEB = """{"data": [{"id": "g7", "fields": {"title": "Junior Programme Officer",
  "city": "Geneva", "source": [{"name": "WHO"}],
  "country": [{"name": "Switzerland", "iso3": "che"}], "type": [{"name": "Job"}],
  "url": "https://reliefweb.int/job/g7"}}]}"""


def test_geneva_ir_graduate_gets_ranked_visa_aware_shortlist() -> None:
    friend = CandidateProfile(
        nationality="CN", degree_country="CH",  # Swiss degree unlocks CH
        field="international relations", languages=["en", "fr"],
        tracks=[Track.private, Track.intl_org],
    )

    agent = ScoutAgent(
        http_get=lambda url: _PA_XML,  # Track A: the public-affairs ATS feed
        discoverers=[SeedDiscoverer(SWISS_SEEDS)],
        board_sources=[ReliefWebSource(http=lambda url, headers=None: _RELIEFWEB, iso3=["CHE"],
                                        appname="test")],
        classifier=VisaSignalClassifier(),  # keyword-only (offline) visa tagging
    )

    result = agent.run(ScoutQuery(DiscoveryQuery(country="CH", industry="Public Affairs")))

    # Scout enriched the public-affairs role from its description ("relocation support").
    pa = next(j for j in result.jobs if j.external_id == "77")
    assert pa.visa_signal is VisaSignal.explicit_yes

    ranked = shortlist(friend, result.jobs)
    assert ranked, "expected at least one viable job"
    assert all(r.feasibility.level is not FeasibilityLevel.red for r in ranked)
    # Both her tracks surfaced and are viable (Swiss degree + intl-org bypass).
    countries_titles = {r.job.title for r in ranked}
    assert "Junior Public Affairs Officer" in countries_titles
    assert "Junior Programme Officer" in countries_titles
