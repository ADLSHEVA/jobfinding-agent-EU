"""Domain-aware keyword extraction and filtering — offline tests.

All tests use fake LLM callables (never hit the network). The prompt construction
and JSON parsing are tested directly; the integration with real Mistral is a manual
smoke test.
"""

import pytest

from job_agent.matching.domain_filter import (
    DomainKeywords,
    _build_prompt,
    _fallback_keywords,
    _parse_response,
    extract_domain_keywords,
    filter_by_domain,
    passes_domain_filter,
)
from job_agent.models.job import Job


def _job(ext: str, title: str, desc: str = "", company: str = "C") -> Job:
    return Job(source="s", external_id=ext, title=title, company=company,
               country="DE", description=desc)


# --- _parse_response ----------------------------------------------------------


def test_parse_valid_json() -> None:
    raw = '{"retrieval_keywords": ["EU policy"], "domain_terms": ["public affairs", "advocacy"]}'
    result = _parse_response(raw)
    assert result.retrieval_keywords == ["EU policy"]
    assert result.domain_terms == ["public affairs", "advocacy"]


def test_parse_json_with_markdown_fences() -> None:
    raw = '```json\n{"retrieval_keywords": ["test"], "domain_terms": ["foo"]}\n```'
    result = _parse_response(raw)
    assert result.retrieval_keywords == ["test"]
    assert result.domain_terms == ["foo"]


def test_parse_invalid_json_returns_empty() -> None:
    result = _parse_response("this is not json at all")
    assert result.retrieval_keywords == []
    assert result.domain_terms == []


def test_parse_missing_keys_returns_empty_lists() -> None:
    result = _parse_response('{"retrieval_keywords": ["a"]}')
    assert result.retrieval_keywords == ["a"]
    assert result.domain_terms == []


# --- _build_prompt ------------------------------------------------------------


def test_prompt_includes_all_fields() -> None:
    prompt = _build_prompt("international relations", ["policy", "advocacy"],
                           "Internship at EU consultancy")
    assert "international relations" in prompt
    assert "policy, advocacy" in prompt
    assert "Internship at EU consultancy" in prompt


def test_prompt_handles_empty_fields() -> None:
    prompt = _build_prompt("", [], "")
    assert "(unspecified)" in prompt
    assert "(none listed)" in prompt


def test_prompt_truncates_long_experience() -> None:
    long_exp = "x " * 5000
    prompt = _build_prompt("field", ["skill"], long_exp)
    # The experience should be truncated to 3000 chars in the prompt
    assert len(prompt) < len(long_exp) + 500


# --- _fallback_keywords ------------------------------------------------------


def test_fallback_for_international_relations() -> None:
    kw = _fallback_keywords("international relations")
    assert "public affairs" in kw.retrieval_keywords
    assert any("policy" in t for t in kw.domain_terms)


def test_fallback_for_computer_science() -> None:
    kw = _fallback_keywords("computer science")
    assert any("software" in t for t in kw.retrieval_keywords)
    assert any("software" in t or "programming" in t for t in kw.domain_terms)


def test_fallback_for_unknown_field() -> None:
    kw = _fallback_keywords("underwater basket weaving")
    assert len(kw.retrieval_keywords) >= 1
    assert len(kw.domain_terms) >= 1


def test_fallback_for_empty_field() -> None:
    kw = _fallback_keywords("")
    assert len(kw.retrieval_keywords) >= 1


# --- extract_domain_keywords --------------------------------------------------


def test_extract_with_fake_llm() -> None:
    def fake_ask(prompt: str) -> str:
        return '{"retrieval_keywords": ["EU affairs", "policy officer"], "domain_terms": ["EU policy", "legislation", "advocacy"]}'

    result = extract_domain_keywords("international relations", ["policy"], "EU internship", fake_ask)
    assert "EU affairs" in result.retrieval_keywords
    assert "EU policy" in result.domain_terms


def test_extract_falls_back_when_no_llm() -> None:
    result = extract_domain_keywords("international relations", [], "")
    assert result.retrieval_keywords  # not empty
    assert result.domain_terms  # not empty
    assert "public affairs" in result.retrieval_keywords


def test_extract_falls_back_on_llm_error() -> None:
    def failing_ask(prompt: str) -> str:
        raise RuntimeError("API down")

    result = extract_domain_keywords("international relations", [], "", failing_ask)
    assert result.retrieval_keywords  # fallback kicks in


def test_extract_falls_back_on_bad_json() -> None:
    def bad_json_ask(prompt: str) -> str:
        return "I cannot comply with that request"

    result = extract_domain_keywords("international relations", [], "", bad_json_ask)
    assert result.retrieval_keywords  # fallback kicks in


# --- passes_domain_filter ----------------------------------------------------


def test_passes_with_matching_domain() -> None:
    job = _job("1", "Policy Officer", "Draft policy briefs and monitor EU legislation.")
    assert passes_domain_filter(job, ["policy", "EU legislation", "advocacy"])


def test_fails_with_wrong_domain() -> None:
    job = _job("2", "Software Engineer",
               "Build microservices with Python and AWS. International team environment.")
    assert not passes_domain_filter(job, ["policy", "EU legislation", "advocacy", "public affairs"])


def test_passes_with_min_hits_threshold() -> None:
    job = _job("3", "Analyst", "Data analysis for international development projects.")
    # Has "international development" but not "policy" or "EU legislation"
    assert passes_domain_filter(job, ["policy", "international development"], min_hits=1)
    assert not passes_domain_filter(job, ["policy", "EU legislation", "public affairs"], min_hits=2)


def test_empty_domain_terms_pass_everything() -> None:
    job = _job("4", "Anything", "Whatever")
    assert passes_domain_filter(job, [])


def test_case_insensitive_matching() -> None:
    job = _job("5", "POLICY OFFICER", "EU LEGISLATION monitoring")
    assert passes_domain_filter(job, ["policy", "eu legislation"])


# --- filter_by_domain --------------------------------------------------------


def test_filter_removes_irrelevant_jobs() -> None:
    jobs = [
        _job("1", "Policy Officer", "Draft policy briefs for EU advocacy."),
        _job("2", "Software Engineer", "Build cloud infrastructure with Python."),
        _job("3", "Public Affairs Consultant", "Stakeholder engagement for EU legislation."),
    ]
    domain = ["policy", "EU legislation", "advocacy", "public affairs"]
    filtered = filter_by_domain(jobs, domain)
    assert len(filtered) == 2
    assert filtered[0].external_id == "1"
    assert filtered[1].external_id == "3"


def test_filter_with_empty_domain_passes_all() -> None:
    jobs = [_job("1", "A", "B"), _job("2", "C", "D")]
    assert len(filter_by_domain(jobs, [])) == 2


def test_filter_preserves_order() -> None:
    jobs = [
        _job("a", "Policy Analyst", "policy work"),
        _job("b", "IT Support", "fix computers"),
        _job("c", "EU Affairs Officer", "EU legislation"),
    ]
    filtered = filter_by_domain(jobs, ["policy", "EU legislation"])
    assert [j.external_id for j in filtered] == ["a", "c"]


# --- realistic scenario: IR candidate vs IT jobs ------------------------------


def test_ir_candidate_filters_out_it_jobs() -> None:
    """Core scenario: IR candidate sees policy + admin/coordination roles, NOT IT."""
    domain = ["public affairs", "policy", "political", "EU legislation",
              "advocacy", "governance", "NGO", "international organization",
              "international affairs", "public policy", "foreign affairs",
              "humanitarian", "peace", "human rights", "diplomacy",
              "public sector", "think tank", "civil society", "diplomatic",
              "international development", "development cooperation",
              "trainee", "assistant", "coordinator", "officer", "intern",
              "UN", "WHO", "UNDP",
              # Transferable-skill roles at private companies
              "project coordination", "stakeholder", "client relations",
              "account management", "office management", "communication",
              "event coordination", "partnership", "liaison"]
    jobs = [
        # --- Should PASS: IR-domain jobs ---
        _job("good1", "Junior Policy Officer — EU Public Affairs",
             "Join our policy team to draft policy briefs, monitor EU legislation."),
        _job("good2", "Trainee — International Development NGO",
             "Support international development programs. Advocacy for EU funding."),
        _job("good5", "Intern - Political Affairs",
             "Assist in monitoring political developments, draft reports on "
             "international affairs, support peace process coordination."),
        _job("good6", "Junior Professional Officer - Human Rights",
             "Support human rights monitoring, assist with advocacy."),
        # --- Should PASS: transferable-skill roles at private companies ---
        _job("good7", "Project Coordinator — Consulting Firm",
             "Coordinate client projects, manage stakeholder communication, "
             "support event coordination for partner meetings."),
        _job("good8", "Junior Account Manager",
             "Manage client relations and partnerships. Liaison between "
             "internal teams and external stakeholders."),
        _job("good9", "Office Assistant — International Company",
             "Support office management, coordinate meetings, handle "
             "communication with partners and clients."),
        # --- Should FAIL: IT/tech jobs ---
        _job("bad1", "Software Engineer (International Team)",
             "We are looking for an international team player to join our engineering "
             "department. You will work on data analysis and cloud infrastructure."),
        _job("bad2", "IT Consultant — Swiss Tech Startup",
             "Join a fast-growing tech company in Zurich. Python, AWS, Kubernetes."),
        _job("bad3", "Data Analyst",
             "Work with large datasets. SQL, Python, Tableau."),
    ]
    filtered = filter_by_domain(jobs, domain)
    ids = [j.external_id for j in filtered]
    # IR-domain jobs pass
    assert "good1" in ids
    assert "good2" in ids
    assert "good5" in ids
    assert "good6" in ids
    # Transferable-skill jobs at private companies also pass
    assert "good7" in ids
    assert "good8" in ids
    assert "good9" in ids
    # IT jobs filtered out
    assert "bad1" not in ids
    assert "bad2" not in ids
    assert "bad3" not in ids
