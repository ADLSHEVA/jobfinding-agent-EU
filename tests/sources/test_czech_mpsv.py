"""Czech MPSV source maps open-data vacancies and flags non-EU-friendly ones to sponsor."""

from __future__ import annotations

import json

from job_agent.discovery.base import DiscoveryQuery
from job_agent.models.job import VisaSignal
from job_agent.sources.aggregators import CzechMpsvSource

_LISTING = """
<a href="volna-mista-prirustek-2026-06-01.json">x</a>
<a href="volna-mista-prirustek-2026-06-02.json">x</a>
"""

_DAY = json.dumps({"polozky": [
    {
        "portalId": 111,
        "referencniCislo": "ref-111",
        "cizinecMimoEu": True,
        "pozadovanaProfese": {"cs": "Automatizační inženýr"},
        "zamestnavatel": {"nazev": "Doosan Bobcat EMEA"},
        "mistoVykonuPrace": {"pracoviste": [{"nazev": "Dobříš"}]},
        "mesicniMzdaOd": 45000,
        "urlAdresa": None,
    },
    {  # not open to non-EU → dropped when non_eu_only
        "portalId": 222, "cizinecMimoEu": False,
        "pozadovanaProfese": {"cs": "Kuchař"}, "zamestnavatel": {"nazev": "Local"},
    },
]})


def _http(url, headers=None):
    return _LISTING if url.endswith("/") else _DAY


def test_mpsv_keeps_non_eu_and_maps_sponsor_signal() -> None:
    src = CzechMpsvSource(_http, recent_files=2)
    jobs = src.fetch(DiscoveryQuery(country="CZ", keywords=[]))

    assert {j.external_id for j in jobs} == {"111"}  # non-EU one only (deduped across days)
    job = jobs[0]
    assert job.company == "Doosan Bobcat EMEA" and job.city == "Dobříš" and job.country == "CZ"
    assert job.visa_signal is VisaSignal.explicit_yes  # non-EU friendly → will sponsor
    assert "ref-111" in (job.url or "")


def test_mpsv_skipped_for_non_czech_country() -> None:
    assert CzechMpsvSource(_http).fetch(DiscoveryQuery(country="DE")) == []
