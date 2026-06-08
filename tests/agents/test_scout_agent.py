"""Scout orchestrator — offline end-to-end, Track A + Track B, failure isolation."""

import pytest

from job_agent.agents import ScoutAgent, ScoutQuery
from job_agent.discovery import DiscoveryQuery, SeedDiscoverer
from job_agent.models.company import ATSPlatform, CompanyTarget
from job_agent.observability import InMemoryObservability
from job_agent.persistence import InMemoryJobStore
from job_agent.sources.intl_org import ReliefWebSource

_PERSONIO = """<?xml version="1.0"?><workzag-jobs>
  <position><id>1</id><name>Junior Developer</name><office>Prague</office></position>
</workzag-jobs>"""

_RELIEFWEB = """{"data": [
  {"id": "g1", "fields": {"title": "Programme Officer", "city": "Geneva",
   "source": [{"name": "WHO"}], "country": [{"name": "Switzerland", "iso3": "che"}],
   "type": [{"name": "Job"}], "url": "https://reliefweb.int/job/g1"}}]}"""


def _router(mapping: dict[str, str]):
    """http_get that serves fixtures by URL, raising for anything unexpected."""
    def _get(url: str) -> str:
        for needle, body in mapping.items():
            if needle in url:
                return body
        raise RuntimeError(f"unexpected fetch: {url}")
    return _get


def _company(handle: str, ats: ATSPlatform = ATSPlatform.personio, **kw) -> CompanyTarget:
    return CompanyTarget(name=f"Co {handle}", country="CZ", ats=ats, ats_handle=handle, **kw)


def test_scout_runs_both_tracks_and_persists() -> None:
    store, obs = InMemoryJobStore(), InMemoryObservability()
    seeds = SeedDiscoverer([_company("acme", industry="IT")])
    # Track A companies use the agent's http_get; the board source carries its own.
    reliefweb = ReliefWebSource(http=lambda url, headers=None: _RELIEFWEB, iso3=["CHE"],
                                appname="test")
    agent = ScoutAgent(
        http_get=_router({"personio": _PERSONIO}),
        discoverers=[seeds],
        board_sources=[reliefweb],
        store=store,
        obs=obs,
    )

    result = agent.run(ScoutQuery(DiscoveryQuery(industry="IT")))

    titles = {j.title for j in result.jobs}
    assert titles == {"Junior Developer", "Programme Officer"}  # Track A + Track B
    assert result.fetched == 2 and result.stored == 2
    assert not result.errors
    assert len(store.all()) == 2
    assert obs.runs[0]["status"] == "success"


def test_one_company_failure_does_not_abort_others() -> None:
    # 'boom' has no fixture → its fetch raises; 'acme' must still come through.
    seeds = SeedDiscoverer([_company("boom"), _company("acme")])
    agent = ScoutAgent(http_get=_router({"acme": _PERSONIO}), discoverers=[seeds])

    result = agent.run(ScoutQuery(DiscoveryQuery(country="CZ")))

    assert [j.title for j in result.jobs] == ["Junior Developer"]
    # A single discovered company's fetch failing is a routine discovery miss, skipped
    # silently — 'acme' still comes through and nothing noisy is surfaced to the user.
    assert result.errors == []


def test_dedupe_across_sources() -> None:
    # Same company discovered twice → jobs deduped on (source, external_id).
    seeds = SeedDiscoverer([_company("acme"), _company("acme")])
    agent = ScoutAgent(http_get=_router({"personio": _PERSONIO}), discoverers=[seeds])

    result = agent.run(ScoutQuery(DiscoveryQuery(country="CZ")))

    assert result.fetched == 2  # fetched twice
    assert result.stored == 1   # deduped to one


def test_run_raises_are_recorded_as_error_status() -> None:
    class Boom:
        def discover(self, query):  # type: ignore[no-untyped-def]
            raise ValueError("kaboom")

    # Discoverer failure is isolated (becomes an error string), so to exercise the
    # observability error path we make the store blow up instead.
    class ExplodingStore:
        def upsert_jobs(self, jobs):  # type: ignore[no-untyped-def]
            raise RuntimeError("db down")

    obs = InMemoryObservability()
    agent = ScoutAgent(http_get=_router({}), store=ExplodingStore(), obs=obs)
    with pytest.raises(RuntimeError):
        agent.run(ScoutQuery(DiscoveryQuery()))
    assert obs.runs[0]["status"] == "error"
    assert obs.runs[0]["error_message"] == "db down"
