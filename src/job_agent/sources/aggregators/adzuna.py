"""Adzuna board source — job aggregator with a free public API.

Adzuna aggregates jobs from career pages, job boards, and recruiters across
Switzerland and many other European countries.  It fills the gap between
JobRoom (Swiss PES only) and JSearch (Google for Jobs) by providing structured
search with salary data, category filters, and location scoping.

API docs: https://developer.adzuna.com/overview
Endpoint: GET https://api.adzuna.com/v1/api/jobs/{country}/search/{page}
Auth:     app_id + app_key (query params), free tier available.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
from typing import Any, Callable

from job_agent.discovery.base import DiscoveryQuery
from job_agent.models.job import Job
from job_agent.sources.base import classify_employment

log = logging.getLogger(__name__)

# (url, headers) -> response text.
HttpJson = Callable[[str, dict[str, str] | None], str]

_BASE = "https://api.adzuna.com/v1/api/jobs"

# Adzuna country codes (ISO-2 lowercased) for our supported markets.
_SUPPORTED_COUNTRIES = {"ch", "de", "at", "fr", "nl", "be", "it", "pl", "cz"}


def _to_job(d: dict[str, Any], country: str) -> Job | None:
    ext_id = d.get("id")
    title = d.get("title")
    if not ext_id or not title:
        return None
    company = (d.get("company") or {}).get("display_name", "")
    loc = d.get("location") or {}
    # Adzuna location.area is a list like ["Europe", "Switzerland", "Genève"]
    area = loc.get("area", [])
    city = loc.get("display_name", "")
    # Try to extract a cleaner city name from the area list
    if len(area) >= 3:
        city = area[-1]
    elif len(area) >= 2 and not city:
        city = area[-1]

    # Build a direct link to the Adzuna detail page (which redirects to employer)
    url = d.get("redirect_url") or ""

    # Description: Adzuna returns it in the "description" field
    desc = d.get("description", "") or ""

    return Job(
        source="adzuna",
        external_id=str(ext_id),
        title=str(title),
        company=company,
        country=country.upper(),
        city=city or None,
        source_type="aggregator",
        description=desc,
        url=url or None,
        employment_type=classify_employment(title, d.get("contract_type")),
    )


class AdzunaSource:
    """``BoardSource`` over the Adzuna API.  Skipped when credentials are missing."""

    name = "adzuna"

    def __init__(
        self,
        http: HttpJson,
        app_id: str = "",
        app_key: str = "",
        pages: int = 1,
        results_per_page: int = 30,
    ) -> None:
        self._http = http
        self._app_id = app_id
        self._app_key = app_key
        self._pages = pages
        self._per_page = results_per_page

    def fetch(self, query: DiscoveryQuery) -> list[Job]:
        if not self._app_id or not self._app_key:
            return []
        if not query.country:
            # Adzuna requires a country code; skip broad/EU-wide queries.
            return []
        country = query.country.lower()
        if country not in _SUPPORTED_COUNTRIES:
            return []

        keywords = " ".join(query.keywords).strip()
        all_jobs: list[Job] = []

        for page in range(1, self._pages + 1):
            params: dict[str, str] = {
                "app_id": self._app_id,
                "app_key": self._app_key,
                "results_per_page": str(self._per_page),
            }
            if keywords:
                params["what"] = keywords
            # Only use "where" if we have a specific city hint in the query
            # (Adzuna's where param is for location, not country — the country
            # is already in the URL path).

            url = f"{_BASE}/{country}/search/{page}?{urllib.parse.urlencode(params)}"
            try:
                raw = self._http(url, {"Accept": "application/json"})
                data = json.loads(raw)
            except Exception:
                log.debug("adzuna: failed to fetch page %d for %s", page, country)
                break

            for item in data.get("results", []):
                job = _to_job(item, country)
                if job is not None:
                    all_jobs.append(job)

        return all_jobs
