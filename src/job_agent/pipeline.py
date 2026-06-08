"""Assemble a production-wired ScoutAgent from the real sources.

Keeps the wiring in one place so the UI (and scripts) get live jobs instead of demo
data. Transports are injected, so the factory is unit-testable offline; only
``production_transports`` actually touches the network (via stdlib urllib).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Callable

from job_agent.agents import ScoutAgent
from job_agent.config import Settings, get_settings
from job_agent.discovery.ats_search import AtsSearchDiscoverer, SearchFn
from job_agent.discovery.base import CompanyDiscoverer
from job_agent.discovery.seed import SeedDiscoverer
from job_agent.models.company import CompanyTarget
from job_agent.observability import ObservabilityStore
from job_agent.persistence import JobStore
from job_agent.sources import HttpGet
from job_agent.sources.aggregators import (
    ArbeitsagenturSource,
    CzechMpsvSource,
    JobRoomSource,
    JSearchSource,
)
from job_agent.sources.board import HttpJson
from job_agent.sources.intl_org import ReliefWebSource
from job_agent.visa.signal import VisaSignalClassifier

# (url, json_body, headers) -> text. Job-Room is POST-based, unlike the GET aggregators.
JsonPost = Callable[[str, dict, Mapping[str, str] | None], str]

# Geneva, Vienna, Brussels, Bonn/Frankfurt, Rome, Copenhagen hubs for Track B.
_INTL_ORG_HUBS = ["CHE", "AUT", "BEL", "DEU", "FRA", "ITA", "DNK"]


def build_live_scout(
    *,
    http_get: HttpGet,
    http_json: HttpJson,
    http_post: JsonPost,
    seeds: list[CompanyTarget] | None = None,
    search_fn: SearchFn | None = None,
    search_cities: int = 3,
    search_max_companies: int | None = None,
    store: JobStore | None = None,
    obs: ObservabilityStore | None = None,
    classifier: VisaSignalClassifier | None = None,
    intl_org_iso3: list[str] | None = None,
    reliefweb_appname: str = "",
    rapidapi_key: str = "",
) -> ScoutAgent:
    """Wire the discovery engine + Layer-1 aggregators + Track-B into one ScoutAgent.

    ``search_fn`` (Brave) enables ``AtsSearchDiscoverer`` — the engine that finds
    actively-hiring companies with no names known upfront. ``search_cities`` and
    ``search_max_companies`` trade breadth for Brave-quota/memory (the latter caps how
    many company feeds get fetched — important on constrained hosts like Streamlit
    Cloud). Filter the cross-border output with ``keep_jobs_in_country`` afterwards.
    """
    discoverers: list[CompanyDiscoverer] = [SeedDiscoverer(seeds or [])]
    if search_fn is not None:
        discoverers.append(AtsSearchDiscoverer(
            search_fn, cities=search_cities, max_companies=search_max_companies))
    # EURES is intentionally omitted: its public endpoint now 404s (dead). JobRoom
    # (Switzerland's official PES) + ATS discovery cover CH; Arbeitsagentur covers DE.
    # ReliefWeb (Track-B intl orgs) only runs when a pre-approved appname is configured.
    board_sources = [
        ArbeitsagenturSource(http_json),
        JobRoomSource(http_post),  # Job-Room uses POST (Switzerland's official PES)
        CzechMpsvSource(http_json),  # Czech official PES open data (incl. non-EU-friendly)
        ReliefWebSource(http_json, iso3=intl_org_iso3 or _INTL_ORG_HUBS,
                        appname=reliefweb_appname),
    ]
    # JSearch (Google for Jobs) reaches established employers beyond LinkedIn / the SME
    # ATS boards — added only when a RapidAPI key is configured.
    if rapidapi_key:
        board_sources.append(JSearchSource(http_json, api_key=rapidapi_key))
    return ScoutAgent(
        http_get=http_get,
        discoverers=discoverers,
        board_sources=board_sources,
        store=store,
        obs=obs,
        classifier=classifier or VisaSignalClassifier(),
    )


def brave_search_fn(settings: Settings | None = None) -> SearchFn | None:
    """A Brave-Search ``SearchFn`` (query → result URLs), or ``None`` if no key set."""
    s = settings if settings is not None else get_settings()
    if not s.brave_api_key:
        return None
    import json
    import time
    import urllib.parse

    from job_agent.sources.http import urllib_http

    last_call = [0.0]  # Brave free tier allows ~1 request/second → space calls out.

    def search(query: str) -> list[str]:
        gap = 1.1 - (time.monotonic() - last_call[0])
        if gap > 0:
            time.sleep(gap)
        last_call[0] = time.monotonic()
        url = "https://api.search.brave.com/res/v1/web/search?" + urllib.parse.urlencode(
            {"q": query, "count": 20}
        )
        try:
            body = urllib_http(url, {"X-Subscription-Token": s.brave_api_key, "Accept": "application/json"})
        except Exception:  # noqa: BLE001 - rate-limit/network blip → skip this query, keep going
            return []
        results = (json.loads(body).get("web") or {}).get("results", [])
        return [r.get("url", "") for r in results]

    return search


def production_transports() -> tuple[HttpGet, HttpJson, JsonPost]:
    """Real stdlib transports: ``http_get(url)`` (ATS), ``http_json(url, headers)``
    (GET board sources, may send auth headers), ``http_post(url, body, headers)`` (Job-Room)."""
    from job_agent.sources.http import urllib_http, urllib_post

    def http_get(url: str) -> str:
        return urllib_http(url)

    def http_json(url: str, headers=None) -> str:
        return urllib_http(url, headers)

    def http_post(url: str, body: dict, headers=None) -> str:
        return urllib_post(url, body, headers)

    return http_get, http_json, http_post
