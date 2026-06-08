"""Job-Room board source — Switzerland's official public employment service.

job-room.ch is run by SECO and lists registered Swiss vacancies (incl. those under
the Stellenmeldepflicht). Switzerland is outside EURES, so this is the compliant CH
baseline. robots.txt disallows the ``/job-search/`` UI page but NOT the API.

Built to the live API (probed 2026): **POST** ``/jobadservice/api/jobAdvertisements
/_search?page=&size=`` with body ``{}`` returns a JSON array of
``{"jobAdvertisement": {"jobContent": {"jobDescriptions":[{title,description}],
"company":{name,website,...}, "location":{city,countryIsoCode,...}}}}``. Keyword
filtering is applied client-side (the request schema rejects unknown fields).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Callable

from job_agent.discovery.base import DiscoveryQuery
from job_agent.models.job import Job
from job_agent.sources.base import classify_employment

# (url, json_body, headers) -> response text.
JsonPost = Callable[[str, dict, Mapping[str, str] | None], str]

_BASE_URL = "https://www.job-room.ch/jobadservice/api/jobAdvertisements/_search"


def _normalize(item: dict[str, Any]) -> Job | None:
    ja = item.get("jobAdvertisement") if isinstance(item.get("jobAdvertisement"), dict) else None
    if ja is None:
        return None
    ext_id = ja.get("id")
    content = ja.get("jobContent") or {}
    descriptions = content.get("jobDescriptions") or []
    first = descriptions[0] if descriptions else {}
    title = first.get("title")
    if not ext_id or not title:
        return None
    company = content.get("company") or {}
    location = content.get("location") or {}
    return Job(
        source="jobroom",
        external_id=str(ext_id),
        title=title,
        company=company.get("name") or "",
        country=(location.get("countryIsoCode") or "CH").upper(),
        city=location.get("city"),
        source_type="pes",
        description=first.get("description", "") or "",
        url=content.get("externalUrl") or f"https://www.job-room.ch/job-search/{ext_id}",
        employment_type=classify_employment(title),
    )


class JobRoomSource:
    name = "jobroom"

    def __init__(self, post: JsonPost, page_size: int = 100) -> None:
        self._post = post
        self._page_size = page_size

    def fetch(self, query: DiscoveryQuery) -> list[Job]:
        url = f"{_BASE_URL}?page=0&size={self._page_size}&sort=score"
        data = json.loads(self._post(url, {}, None))  # empty body = recent CH vacancies
        items = data if isinstance(data, list) else (data.get("content") or [])
        jobs = [j for j in (_normalize(i) for i in items) if j is not None]

        keywords = [k.lower() for k in query.keywords]
        if keywords:  # the API rejects extra filter fields, so filter client-side
            # Use ``any()`` — the downstream domain filter handles relevance more
            # precisely.  Here we just need to keep the feed from being 100% noise;
            # being too aggressive risks dropping viable junior-level postings.
            jobs = [
                j for j in jobs
                if any(k in f"{j.title} {j.description}".lower() for k in keywords)
            ]
        return jobs
