"""ReliefWeb jobs adapter (Track B).

Public API: ``https://api.reliefweb.int/v2/jobs`` (JSON, no auth). Returns UN / NGO
/ humanitarian roles worldwide; we filter by country (e.g. CHE for Geneva) and tag
them ``track=intl_org`` so the visa engine applies the international-organisation
legal route (host-country legitimation, not a national work permit).

Since 2025-11-01 ReliefWeb requires a PRE-APPROVED ``appname`` (register a short form
at https://reliefweb.int/help/api). An unregistered appname returns HTTP 403, so the
``ReliefWebSource`` below is skipped unless an approved appname is configured
(``RELIEFWEB_APPNAME`` secret / env). v1 was decommissioned (HTTP 410).
"""

import json
from typing import Any

from job_agent.discovery.base import DiscoveryQuery
from job_agent.models.candidate import Track
from job_agent.models.job import EmploymentType, Job
from job_agent.sources.base import HttpGet, classify_employment
from job_agent.sources.board import HttpJson

# Minimal ISO-3166 alpha-3 -> alpha-2 for the European hubs we care about.
_ISO3_TO_ISO2 = {
    "CHE": "CH", "AUT": "AT", "BEL": "BE", "LUX": "LU", "NLD": "NL", "DEU": "DE",
    "FRA": "FR", "ITA": "IT", "DNK": "DK", "POL": "PL", "CZE": "CZ", "ESP": "ES",
}


def _employment_from_type(type_name: str, title: str) -> EmploymentType:
    name = type_name.lower()
    if "intern" in name:
        return EmploymentType.internship
    if "consult" in name:
        return EmploymentType.other
    return classify_employment(title)


class ReliefWebAdapter:
    def __init__(self, appname: str = "eu-job-agent") -> None:
        self._appname = appname or "eu-job-agent"

    def feed_url(self, country_iso3: str, limit: int = 50) -> str:
        return (
            "https://api.reliefweb.int/v2/jobs"
            f"?appname={self._appname}&limit={limit}"
            "&fields[include][]=title&fields[include][]=source&fields[include][]=country"
            "&fields[include][]=city&fields[include][]=url&fields[include][]=type"
            "&fields[include][]=body"
            f"&filter[field]=country.iso3&filter[value]={country_iso3.lower()}"
        )

    def parse(self, body: str, country_iso2: str) -> list[Job]:
        data: dict[str, Any] = json.loads(body)
        jobs: list[Job] = []
        for item in data.get("data", []):
            fields = item.get("fields", {})
            ext_id = str(item.get("id", "")).strip()
            title = (fields.get("title") or "").strip()
            if not ext_id or not title:
                continue
            org = (fields.get("source") or [{}])[0].get("name", "Unknown organisation")
            type_name = (fields.get("type") or [{}])[0].get("name", "")
            jobs.append(
                Job(
                    source="reliefweb",
                    external_id=ext_id,
                    title=title,
                    company=org,
                    country=country_iso2,
                    city=fields.get("city"),
                    track=Track.intl_org,
                    source_type="intl_org",
                    description=fields.get("body", "") or "",
                    url=fields.get("url"),
                    employment_type=_employment_from_type(type_name, title),
                )
            )
        return jobs


def fetch_intl_org_jobs(
    country_iso3: str,
    http_get: HttpGet,
    adapter: ReliefWebAdapter | None = None,
) -> list[Job]:
    """Fetch Track-B roles for a hub country (e.g. ``"CHE"`` for Geneva)."""
    adapter = adapter or ReliefWebAdapter()
    iso2 = _ISO3_TO_ISO2.get(country_iso3.upper(), country_iso3.upper()[:2])
    body = http_get(adapter.feed_url(country_iso3))
    return adapter.parse(body, iso2)


_ISO2_TO_ISO3 = {v: k for k, v in _ISO3_TO_ISO2.items()}


class ReliefWebSource:
    """``BoardSource`` wrapper over ReliefWeb for Track B (intl organisations).

    Scans the configured hub countries (e.g. ``["CHE"]`` for Geneva); if the query
    names a country we map it to ISO-3 and scope to that one instead.
    """

    name = "reliefweb"

    def __init__(self, http: HttpJson, iso3: list[str] | None = None,
                 appname: str = "") -> None:
        self._http = http
        self._iso3 = iso3 or ["CHE"]
        self._appname = appname
        self._adapter = ReliefWebAdapter(appname or "eu-job-agent")

    def fetch(self, query: DiscoveryQuery) -> list[Job]:
        # ReliefWeb requires a pre-approved appname since 2025-11-01; without one the
        # API 403s. Skip cleanly rather than spamming the UI with errors. Register at
        # https://reliefweb.int/help/api and set RELIEFWEB_APPNAME to enable.
        if not self._appname:
            return []
        if query.country:
            countries = [_ISO2_TO_ISO3.get(query.country.upper(), query.country.upper())]
        else:
            countries = self._iso3
        jobs: list[Job] = []
        for iso3 in countries:
            body = self._http(self._adapter.feed_url(iso3), None)
            iso2 = _ISO3_TO_ISO2.get(iso3.upper(), iso3.upper()[:2])
            jobs.extend(self._adapter.parse(body, iso2))
        return jobs
