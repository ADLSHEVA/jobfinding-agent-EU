"""build_live_scout wires real sources into one ScoutAgent (offline via fakes)."""

import json

from job_agent.discovery import DiscoveryQuery
from job_agent.agents import ScoutQuery
from job_agent.models.company import ATSPlatform, CompanyTarget
from job_agent.persistence import InMemoryJobStore
from job_agent.pipeline import build_live_scout

_PERSONIO = '<?xml version="1.0"?><workzag-jobs><position><id>1</id><name>Dev</name></position></workzag-jobs>'
_RELIEFWEB = """{"data": [{"id": "g1", "fields": {"title": "Programme Officer", "city": "Geneva",
  "source": [{"name": "WHO"}], "country": [{"name": "Switzerland", "iso3": "che"}],
  "type": [{"name": "Job"}]}}]}"""
_ADZUNA = json.dumps({"count": 1, "results": [
    {"id": 99, "title": "Policy Trainee", "company": {"display_name": "Adzuna Co"},
     "location": {"display_name": "Bern", "area": ["Europe", "Switzerland", "Bern"]},
     "description": "Policy research."}
]})


def test_build_live_scout_fetches_ats_seed_and_board_sources() -> None:
    seed = CompanyTarget(name="Acme", country="CZ", ats=ATSPlatform.personio, ats_handle="acme")

    def http_get(url):  # ATS seed feeds
        return _PERSONIO

    def http_json(url, headers=None):  # GET board sources
        if "reliefweb" in url:
            return _RELIEFWEB
        return "{}"  # other aggregators parse empty defensively → []

    def http_post(url, body, headers=None):  # Job-Room (POST)
        return "[]"

    store = InMemoryJobStore()
    scout = build_live_scout(http_get=http_get, http_json=http_json, http_post=http_post,
                             seeds=[seed], store=store, intl_org_iso3=["CHE"],
                             reliefweb_appname="test")
    result = scout.run(ScoutQuery(DiscoveryQuery(country="CZ")))

    titles = {j.title for j in result.jobs}
    assert "Dev" in titles            # from the ATS seed company
    assert "Programme Officer" in titles  # from ReliefWeb (Track B)
    assert not result.errors          # empty aggregator responses parse cleanly
    assert store.all()                # persisted


def test_adzuna_wired_when_credentials_present() -> None:
    def http_get(url):
        return _PERSONIO

    def http_json(url, headers=None):
        if "adzuna" in url:
            return _ADZUNA
        if "reliefweb" in url:
            return _RELIEFWEB
        return "{}"

    def http_post(url, body, headers=None):
        return "[]"

    scout = build_live_scout(http_get=http_get, http_json=http_json, http_post=http_post,
                             seeds=[], intl_org_iso3=["CHE"], reliefweb_appname="test",
                             adzuna_app_id="id", adzuna_app_key="key")
    result = scout.run(ScoutQuery(DiscoveryQuery(country="CH")))

    titles = {j.title for j in result.jobs}
    assert "Policy Trainee" in titles  # from Adzuna
