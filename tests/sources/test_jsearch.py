"""JSearch source maps Google-for-Jobs results to Job and is skipped without a key."""

from __future__ import annotations

import json

from job_agent.discovery.base import DiscoveryQuery
from job_agent.sources.aggregators import JSearchSource

_SAMPLE = json.dumps({
    "data": [
        {
            "job_id": "abc123",
            "job_title": "Junior Manufacturing Engineer",
            "employer_name": "Doosan Bobcat EMEA",
            "job_city": "Dobříš",
            "job_country": "CZ",
            "job_description": "Entry-level role supporting production lines.",
            "job_apply_link": "https://careers.bobcat.com/job/abc123",
            "job_employment_type": "FULLTIME",
        },
        {"job_id": "", "job_title": "skipped — no id"},  # invalid → dropped
    ]
})


def test_jsearch_maps_results_and_keeps_apply_link() -> None:
    captured: dict[str, object] = {}

    def http(url, headers=None):
        captured["url"], captured["headers"] = url, dict(headers or {})
        return _SAMPLE

    src = JSearchSource(http, api_key="k")
    jobs = src.fetch(DiscoveryQuery(country="CZ", keywords=["automotive", "manufacturing"]))

    assert [j.external_id for j in jobs] == ["abc123"]  # invalid row dropped
    job = jobs[0]
    assert job.company == "Doosan Bobcat EMEA" and job.country == "CZ" and job.city == "Dobříš"
    assert job.url == "https://careers.bobcat.com/job/abc123"  # direct employer link
    assert "country=cz" in captured["url"] and "automotive" in captured["url"]
    assert captured["headers"]["X-RapidAPI-Key"] == "k"


def test_jsearch_skipped_without_key() -> None:
    def http(url, headers=None):  # must never be called
        raise AssertionError("should not hit the network without a key")

    assert JSearchSource(http, api_key="").fetch(DiscoveryQuery(country="CZ")) == []
