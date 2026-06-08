"""Czech MPSV open-data source — the official Czech public employment service.

The Czech Ministry of Labour (MPSV / Úřad práce) publishes ALL registered vacancies as
open data, so established employers that recruit through their own systems (incl. big
manufacturers like Bobcat in Dobříš) appear here too — they're legally required to
register openings. This is the Czech equivalent of Switzerland's JobRoom.

The full dump is ~170 MB (too big to load live), but daily *increment* files are tiny
(<0.5 MB). We fetch the most recent few and keep roles flagged ``cizinecMimoEu`` — open
to non-EU workers — mapping that to an explicit "will sponsor" visa signal, which is
exactly what a non-EU junior needs. No API key (open data).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from typing import Any, Callable

from job_agent.discovery.base import DiscoveryQuery
from job_agent.models.job import Job, VisaSignal
from job_agent.sources.base import classify_employment

HttpJson = Callable[[str, Mapping[str, str] | None], str]

_BASE = "https://data.mpsv.cz/od/soubory/volna-mista-prirustek/"
_FILE_RE = re.compile(r"volna-mista-prirustek-(\d{4}-\d{2}-\d{2})\.json(?![.\w])")


def _city(misto: dict[str, Any] | None) -> str | None:
    if not isinstance(misto, dict):
        return None
    for prac in (misto.get("pracoviste") or []):
        # ``nazev`` is usually the town (e.g. "Olomouc"); fall back to the street name.
        name = prac.get("nazev")
        if name:
            return name
        ulice = ((prac.get("adresa") or {}).get("ulice") or {}).get("nazev")
        if ulice:
            return ulice
    return None


def _to_job(d: dict[str, Any]) -> Job | None:
    ext_id = d.get("portalId") or d.get("referencniCislo")
    title = (d.get("pozadovanaProfese") or {}).get("cs")
    if not ext_id or not title:
        return None
    employer = (d.get("zamestnavatel") or {}).get("nazev") or "Neuvedeno (MPSV)"
    open_non_eu = bool(d.get("cizinecMimoEu"))
    salary = d.get("mesicniMzdaOd")
    desc_bits = []
    if salary:
        desc_bits.append(f"Mzda od {salary} CZK/měsíc.")
    if open_non_eu:
        desc_bits.append("Zaměstnavatel přijímá uchazeče ze zemí mimo EU "
                         "(employee-card / non-EU friendly).")
    ref = d.get("referencniCislo")
    return Job(
        source="mpsv",
        external_id=str(ext_id),
        title=str(title),
        company=employer,
        country="CZ",
        city=_city(d.get("mistoVykonuPrace")),
        source_type="pes",
        description=" ".join(desc_bits),
        url=d.get("urlAdresa")
        or (f"https://www.uradprace.cz/web/cz/volna-mista-v-cr?ref={ref}" if ref else None),
        # A vacancy registered as open to non-EU workers is effectively an explicit
        # willingness to sponsor — the single biggest lever for a non-EU junior.
        visa_signal=VisaSignal.explicit_yes if open_non_eu else VisaSignal.unknown,
        employment_type=classify_employment(str(title)),
    )


class CzechMpsvSource:
    """Official Czech vacancies (open data). Runs only for CZ / Europe-wide searches."""

    name = "mpsv"

    def __init__(self, http: HttpJson, recent_files: int = 2, non_eu_only: bool = True,
                 max_jobs: int = 150) -> None:
        self._http = http
        self._recent = recent_files
        self._non_eu_only = non_eu_only
        self._max_jobs = max_jobs

    def _recent_urls(self) -> list[str]:
        listing = self._http(_BASE, None)
        dates = sorted(set(_FILE_RE.findall(listing)))
        return [f"{_BASE}volna-mista-prirustek-{d}.json" for d in dates[-self._recent:]]

    def fetch(self, query: DiscoveryQuery) -> list[Job]:
        # Czech-only source: skip when a different country is explicitly targeted.
        if query.country and query.country.upper() != "CZ":
            return []
        jobs: list[Job] = []
        seen: set[str] = set()
        for url in self._recent_urls():
            try:
                items = json.loads(self._http(url, None)).get("polozky") or []
            except Exception:  # noqa: BLE001 - one daily file failing must not abort the rest
                continue
            for d in items:
                if self._non_eu_only and not d.get("cizinecMimoEu"):
                    continue
                job = _to_job(d)
                if job and job.external_id not in seen:
                    seen.add(job.external_id)
                    jobs.append(job)
        # Optional keyword narrowing (the feed isn't keyword-searchable server-side).
        kw = [k.lower() for k in query.keywords]
        if kw:
            jobs = [j for j in jobs
                    if any(k in f"{j.title} {j.description}".lower() for k in kw)]
        return jobs[:self._max_jobs]  # bound the volume sent into ranking
