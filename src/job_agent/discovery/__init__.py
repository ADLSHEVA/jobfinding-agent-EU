"""Company-discovery layer — *which* companies to monitor, and which ATS they use.

Pluggable strategies behind one ``CompanyDiscoverer`` protocol so a client can run
either a narrow query (specific country + industry) or a broad sweep:

- ``AtsSearchDiscoverer`` — search ATS domains to find companies ACTIVELY hiring
                            (the real discovery engine: no company names needed).
- ``SeedDiscoverer``      — curated lists (fastest, highest precision).
- ``AtsDetectDiscoverer`` — fingerprint a known company's site for its ATS + handle.
- ``RegistryDiscoverer``  — national business-register open data (widest, lowest yield).

All return ``CompanyTarget`` objects that the Layer-2 ATS adapters can fetch.
"""

from job_agent.discovery.ats_search import (
    AtsSearchDiscoverer,
    keep_jobs_in_country,
    keep_jobs_in_europe,
)
from job_agent.discovery.base import CompanyDiscoverer, DiscoveryQuery
from job_agent.discovery.fingerprint import AtsDetectDiscoverer, detect_ats
from job_agent.discovery.registry import (
    AresClient,
    CompanyRecord,
    RegistryClient,
    RegistryDiscoverer,
    ZefixClient,
)
from job_agent.discovery.resolve import FileCache, SearchDomainResolver
from job_agent.discovery.seed import SeedDiscoverer

__all__ = [
    "AresClient",
    "AtsDetectDiscoverer",
    "AtsSearchDiscoverer",
    "CompanyDiscoverer",
    "CompanyRecord",
    "DiscoveryQuery",
    "FileCache",
    "RegistryClient",
    "RegistryDiscoverer",
    "SearchDomainResolver",
    "SeedDiscoverer",
    "ZefixClient",
    "detect_ats",
    "keep_jobs_in_country",
    "keep_jobs_in_europe",
]
