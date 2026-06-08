"""JSearch (RapidAPI) board source — aggregates Google for Jobs.

Unlike the ATS-handle discovery (which only finds SMEs on personio/greenhouse/lever),
JSearch surfaces postings indexed by Google for Jobs — including ESTABLISHED employers
that recruit through their own career pages (Workday/SuccessFactors/etc.) rather than
LinkedIn, in every country incl. Czechia. Apply links point at the original posting.

Needs a free RapidAPI key (``RAPIDAPI_KEY``). Without it the source is skipped.
API: ``GET https://jsearch.p.rapidapi.com/search?query=<text>&country=<iso2>&page=1``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable

from job_agent.discovery.base import DiscoveryQuery
from job_agent.models.job import Job
from job_agent.sources.base import classify_employment

# (url, headers) -> response text.
HttpJson = Callable[[str, Mapping[str, str] | None], str]

_HOST = "jsearch.p.rapidapi.com"
_URL = "https://jsearch.p.rapidapi.com/search"


def _to_job(d: dict[str, Any], fallback_country: str = "") -> Job | None:
    ext_id = d.get("job_id")
    title = d.get("job_title")
    if not ext_id or not title:
        return None
    # Some Google-for-Jobs rows omit the structured country; the API already filtered
    # by the requested country, so stamp that as the fallback (else the country filter
    # downstream would wrongly drop the job).
    country = (d.get("job_country") or fallback_country or "").upper()
    title = str(title)
    return Job(
        source="jsearch",
        external_id=str(ext_id),
        title=title,
        company=d.get("employer_name") or "",
        country=country,
        city=d.get("job_city") or d.get("job_state") or None,
        source_type="aggregator",
        description=d.get("job_description", "") or "",
        # Prefer the direct employer apply link; fall back to the Google-for-Jobs link.
        url=d.get("job_apply_link") or d.get("job_google_link"),
        employment_type=classify_employment(title, d.get("job_employment_type")),
    )


class JSearchSource:
    """``BoardSource`` over JSearch/Google-for-Jobs. Skipped when no API key is set."""

    name = "jsearch"

    def __init__(self, http: HttpJson, api_key: str = "", pages: int = 1) -> None:
        self._http = http
        self._key = api_key
        self._pages = pages

    def fetch(self, query: DiscoveryQuery) -> list[Job]:
        # Needs a key AND a country: JSearch defaults to the US when no country is given,
        # which only wastes a (rate-limited) call on a Europe search. The Europe-wide mode
        # therefore skips it; per-country mode drives it.
        if not self._key or not query.country:
            return []
        import urllib.parse

        country = query.country.lower()
        keywords = " ".join(query.keywords).strip() or "jobs"
        params = {"query": keywords, "page": "1", "num_pages": str(self._pages),
                  "country": country}
        url = f"{_URL}?{urllib.parse.urlencode(params)}"
        headers = {"X-RapidAPI-Key": self._key, "X-RapidAPI-Host": _HOST,
                   "Accept": "application/json"}
        data = json.loads(self._http(url, headers)).get("data") or []
        return [j for j in (_to_job(d, country.upper()) for d in data) if j is not None]
