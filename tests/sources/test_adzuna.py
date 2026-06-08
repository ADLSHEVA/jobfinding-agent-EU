"""Adzuna aggregator — offline tests using fixture JSON."""

import json

from job_agent.discovery.base import DiscoveryQuery
from job_agent.sources.aggregators.adzuna import AdzunaSource, _to_job


_FIXTURE = {
    "count": 2,
    "results": [
        {
            "id": 12345,
            "title": "Junior Policy Analyst",
            "company": {"display_name": "Geneva Consulting SA"},
            "location": {"display_name": "Genève", "area": ["Europe", "Switzerland", "Genève"]},
            "description": "Draft policy briefs and support stakeholder engagement.",
            "redirect_url": "https://www.adzuna.ch/jobs/detail/12345",
            "contract_type": "permanent",
        },
        {
            "id": 67890,
            "title": "Project Coordinator — NGO",
            "company": {"display_name": "International Development Org"},
            "location": {"display_name": "Bern", "area": ["Europe", "Switzerland", "Bern"]},
            "description": "Coordinate development projects, liaise with partners.",
            "redirect_url": "https://www.adzuna.ch/jobs/detail/67890",
        },
    ],
}


def _fake_http(url: str, headers=None) -> str:
    return json.dumps(_FIXTURE)


def test_adzuna_fetches_and_normalizes() -> None:
    source = AdzunaSource(_fake_http, app_id="test", app_key="test")
    jobs = source.fetch(DiscoveryQuery(country="CH", keywords=["policy", "analyst"]))
    assert len(jobs) == 2
    assert jobs[0].source == "adzuna"
    assert jobs[0].external_id == "12345"
    assert jobs[0].title == "Junior Policy Analyst"
    assert jobs[0].company == "Geneva Consulting SA"
    assert jobs[0].country == "CH"
    assert jobs[0].city == "Genève"
    assert jobs[0].url == "https://www.adzuna.ch/jobs/detail/12345"


def test_adzuna_skipped_without_credentials() -> None:
    source = AdzunaSource(_fake_http, app_id="", app_key="")
    jobs = source.fetch(DiscoveryQuery(country="CH", keywords=["policy"]))
    assert jobs == []


def test_adzuna_skipped_without_country() -> None:
    source = AdzunaSource(_fake_http, app_id="test", app_key="test")
    jobs = source.fetch(DiscoveryQuery(country=None, keywords=["policy"]))
    assert jobs == []


def test_adzuna_skips_unsupported_country() -> None:
    source = AdzunaSource(_fake_http, app_id="test", app_key="test")
    jobs = source.fetch(DiscoveryQuery(country="US", keywords=["policy"]))
    assert jobs == []


def test_to_job_handles_missing_fields() -> None:
    result = _to_job({"id": 1, "title": "Test"}, "CH")
    assert result is not None
    assert result.title == "Test"
    assert result.company == ""


def test_to_job_returns_none_without_id_or_title() -> None:
    assert _to_job({}, "CH") is None
    assert _to_job({"id": 1}, "CH") is None
    assert _to_job({"title": "X"}, "CH") is None


def test_adzuna_passes_keywords_as_query() -> None:
    captured_urls = []

    def capturing_http(url, headers=None):
        captured_urls.append(url)
        return json.dumps({"count": 0, "results": []})

    source = AdzunaSource(capturing_http, app_id="id", app_key="key")
    source.fetch(DiscoveryQuery(country="CH", keywords=["public", "affairs"]))
    assert len(captured_urls) == 1
    assert "what=public+affairs" in captured_urls[0]
    assert "app_id=id" in captured_urls[0]
    assert "/ch/search/" in captured_urls[0]
