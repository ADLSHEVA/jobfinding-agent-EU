"""Discover hiring companies by SEARCHING the ATS domains — no names known upfront.

This is the discovery engine's core trick. Instead of starting from a registry full
of dead shells (ARES) or asking the user for company names, we search the public ATS
job-board domains across the target country's major cities
(``site:jobs.personio.de zürich``, ``site:jobs.lever.co geneva`` …). Every hit is a
company *actively hiring on an ATS right now*; the result URL carries the ATS handle,
so we can pull its structured feed immediately.

Yield scales with **breadth**: cities × ATS domains. The Brave web API caps a single
query at 20 results, so we widen instead — several cities and several ATS domains per
country. Each query is one Brave call (quota-aware: tune ``cities``).
"""

from __future__ import annotations

from typing import Callable

from job_agent.discovery.base import DiscoveryQuery
from job_agent.discovery.fingerprint import detect_ats
from job_agent.models.company import ATSPlatform, CompanyTarget
from job_agent.models.job import Job

# search_fn(query) -> list of result URLs
SearchFn = Callable[[str], list[str]]

# Public ATS board domains to search (the handle lives in the result URL). Multiple
# domains per platform widen coverage (e.g. Personio's .de and .com tenants).
_ATS_DOMAINS: dict[ATSPlatform, list[str]] = {
    ATSPlatform.personio: ["jobs.personio.de", "jobs.personio.com"],
    ATSPlatform.greenhouse: ["boards.greenhouse.io", "job-boards.greenhouse.io"],
    ATSPlatform.lever: ["jobs.lever.co"],
    ATSPlatform.recruitee: ["recruitee.com"],
}

# Per-country terms. The FIRST few are distinct major cities (used to widen the
# search); the rest are spelling variants used when filtering jobs by location.
COUNTRY_TERMS: dict[str, list[str]] = {
    "CZ": ["praha", "brno", "ostrava", "plzen", "olomouc", "liberec",
           "prague", "prag", "czech", "česko", "česká", "czechia"],
    "CH": ["zürich", "geneva", "basel", "bern", "lausanne",
           "zurich", "genève", "genf", "switzerland", "schweiz", "suisse", "svizzera"],
    "AT": ["wien", "graz", "linz", "salzburg", "vienna", "austria", "österreich"],
    "PL": ["warszawa", "kraków", "wrocław", "gdańsk", "warsaw", "krakow", "wroclaw",
           "poland", "polska"],
    "NL": ["amsterdam", "rotterdam", "utrecht", "eindhoven", "the hague", "den haag",
           "netherlands"],
    "DE": ["berlin", "münchen", "hamburg", "köln", "frankfurt", "munich",
           "germany", "deutschland"],
    # Policy / international-relations hubs (EU institutions, intl law, UN agencies).
    "BE": ["brussels", "bruxelles", "brussel", "antwerp", "antwerpen", "ghent", "gent",
           "leuven", "belgium", "belgique", "belgië"],
    "FR": ["paris", "lyon", "marseille", "strasbourg", "lille", "toulouse",
           "france", "français"],
    "IT": ["rome", "roma", "milan", "milano", "turin", "torino", "florence", "firenze",
           "italy", "italia"],
}


def _search_cities(country: str | None, n: int) -> list[str]:
    if not country:
        return [""]
    return (COUNTRY_TERMS.get(country.upper()) or [country])[:n]


class AtsSearchDiscoverer:
    def __init__(
        self,
        search_fn: SearchFn,
        *,
        platforms: list[ATSPlatform] | None = None,
        cities: int = 3,
        max_companies: int | None = None,
    ) -> None:
        self._search = search_fn
        self._platforms = platforms or list(_ATS_DOMAINS)
        self._cities = cities
        self._max_companies = max_companies

    def discover(self, query: DiscoveryQuery) -> list[CompanyTarget]:
        cities = _search_cities(query.country, self._cities)
        keywords = " ".join(query.keywords)
        found: dict[tuple[ATSPlatform, str], CompanyTarget] = {}
        for platform in self._platforms:
            for domain in _ATS_DOMAINS.get(platform, []):
                for city in cities:
                    # Stop issuing searches once we have enough companies (caps Brave
                    # quota AND the downstream fetch — important on constrained hosts).
                    if self._max_companies and len(found) >= self._max_companies:
                        return list(found.values())
                    q = " ".join(p for p in (f"site:{domain}", city, keywords) if p)
                    for url in self._search(q):
                        plat, handle = detect_ats(url)
                        if plat is not ATSPlatform.unknown and handle:
                            found.setdefault(
                                (plat, handle),
                                CompanyTarget(name=handle, country=query.country or "",
                                              industry=query.industry, ats=plat,
                                              ats_handle=handle, discovered_via="ats_search"),
                            )
        return list(found.values())


def keep_jobs_in_country(jobs: list[Job], country: str) -> list[Job]:
    """Filter ATS jobs to those located in ``country``.

    Search-discovered tenants are cross-border, so we keep only postings whose
    **city** is in the target market. Matching on city (not the description) avoids
    false positives from multinationals that merely *mention* the country elsewhere.
    """
    terms = COUNTRY_TERMS.get(country.upper(), [country.lower()])
    return [job for job in jobs if any(t in (job.city or "").lower() for t in terms)]
