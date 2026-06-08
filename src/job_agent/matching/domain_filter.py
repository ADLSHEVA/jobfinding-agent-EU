"""Domain-aware keyword extraction and filtering.

The first layer of relevance: before any embedding or scoring, we use a cheap LLM
call (Mistral-small) to extract DOMAIN-SPECIFIC search terms from the candidate
profile. These serve two purposes:

1. **Retrieval keywords** — fed into Brave Search / JSearch / JobRoom queries so
   the sources return jobs in the right domain (not generic "international" matches).
2. **Domain terms** — a set of core domain phrases that a relevant posting MUST
   contain at least one of.  Posts with zero domain hits are from the wrong industry
   entirely (e.g. an IT job that merely mentions "international team") and are
   filtered out before ranking.

This module is deliberately separated from the main LLM client (DeepSeek) so it
can use a cheaper/faster model (Mistral-small) without interfering with CV parsing
or cover-letter generation.  If the keyword LLM is not configured, every function
degrades gracefully to the existing keyword extraction.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from job_agent.models.job import Job

log = logging.getLogger(__name__)

# --- prompt -------------------------------------------------------------------

_PROMPT_TEMPLATE = (
    "You are a job-search query builder for a European job board targeting "
    "junior international graduates.\n\n"
    "Given this candidate profile:\n"
    "- Field: {field}\n"
    "- Skills: {skills}\n"
    "- Experience: {experience}\n\n"
    "Generate TWO sets of search terms:\n"
    '1. "retrieval_keywords": 3-5 keywords/phrases for job-board search queries. '
    "These must maximize recall for relevant roles while MINIMIZING noise from "
    "unrelated fields (especially IT, software engineering, data science, finance).\n"
    '2. "domain_terms": 8-12 short phrases (1-3 words each) that a relevant '
    "job posting MIGHT contain.  Be INCLUSIVE — include BOTH core domain terms "
    "AND broader adjacent terms.  A junior trainee posting at an NGO or public "
    "institution will not always use the same vocabulary as a senior role.\n\n"
    "RULES for domain_terms:\n"
    "- Include CORE terms (the heart of the field): e.g. 'public affairs', "
    "'policy', 'political', 'legislation', 'advocacy', 'governance'\n"
    "- Include BROADER terms (adjacent fields, org types): e.g. 'NGO', "
    "'international organization', 'public sector', 'think tank', 'civil society', "
    "'humanitarian', 'peace', 'human rights', 'diplomacy'\n"
    "- Include ROLE terms (common junior titles): e.g. 'trainee', 'assistant', "
    "'coordinator', 'officer', 'researcher', 'intern', 'fellow'\n"
    "- Include FIELD-SPECIFIC compound terms: e.g. 'political affairs', "
    "'international affairs', 'public policy', 'foreign affairs', "
    "'development cooperation'\n"
    "- NEVER use ultra-generic single words: 'team', 'communication', "
    "'experience', 'skills', 'work', 'data', 'services'\n"
    "- Include terms in French/German if standard in the field\n\n"
    "Reply with ONLY a JSON object, no markdown fences:\n"
    '{{"retrieval_keywords": ["...", "..."], "domain_terms": ["...", "..."]}}'
)


@dataclass
class DomainKeywords:
    """Extracted domain-specific search terms."""

    retrieval_keywords: list[str] = field(default_factory=list)
    domain_terms: list[str] = field(default_factory=list)


def _build_prompt(field: str, skills: list[str], experience: str) -> str:
    """Build the LLM prompt from candidate profile fields."""
    return _PROMPT_TEMPLATE.format(
        field=field or "(unspecified)",
        skills=", ".join(skills) or "(none listed)",
        experience=(experience or "")[:3000],  # bound token count
    )


def _parse_response(raw: str) -> DomainKeywords:
    """Parse LLM JSON response, stripping markdown fences if present."""
    # Strip ```json ... ``` fences
    cleaned = re.sub(r"```(?:json)?\s*", "", raw)
    cleaned = re.sub(r"```\s*$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        log.warning("domain_filter: failed to parse LLM response as JSON: %s", raw[:200])
        return DomainKeywords()
    return DomainKeywords(
        retrieval_keywords=list(data.get("retrieval_keywords", [])),
        domain_terms=list(data.get("domain_terms", [])),
    )


# --- hardcoded fallback for when no LLM is configured ---

_FIELD_FALLBACKS: dict[str, DomainKeywords] = {
    "international relations": DomainKeywords(
        retrieval_keywords=["public affairs", "EU policy", "international development",
                            "diplomacy", "advocacy specialist", "political affairs"],
        domain_terms=["public affairs", "policy", "political", "EU legislation",
                      "advocacy", "governance", "NGO", "international organization",
                      "international affairs", "public policy", "foreign affairs",
                      "humanitarian", "peace", "human rights", "diplomacy",
                      "public sector", "think tank", "civil society", "diplomatic",
                      "international development", "development cooperation",
                      "trainee", "assistant", "coordinator", "officer", "intern"],
    ),
    "computer science": DomainKeywords(
        retrieval_keywords=["software engineer", "full stack developer",
                            "backend developer", "DevOps engineer"],
        domain_terms=["software", "programming", "developer", "engineering",
                      "backend", "frontend", "DevOps", "cloud", "API",
                      "code", "application"],
    ),
    "data science": DomainKeywords(
        retrieval_keywords=["data analyst", "data scientist", "machine learning engineer",
                            "business intelligence"],
        domain_terms=["data science", "machine learning", "analytics", "data pipeline",
                      "statistical", "Python", "SQL", "visualization", "dataset"],
    ),
    "business": DomainKeywords(
        retrieval_keywords=["business analyst", "management trainee", "consultant",
                            "business development"],
        domain_terms=["business", "consulting", "strategy", "operations",
                      "sales", "marketing", "finance", "client", "commercial",
                      "trainee", "graduate program"],
    ),
}


def _fallback_keywords(field: str) -> DomainKeywords:
    """Hardcoded fallback when no LLM is configured."""
    field_lower = field.lower().strip()
    for key, kw in _FIELD_FALLBACKS.items():
        if key in field_lower or field_lower in key:
            return kw
    # Generic fallback: use the field name itself as the domain term
    if field_lower and len(field_lower) > 3:
        return DomainKeywords(
            retrieval_keywords=[field_lower, f"{field_lower} junior", f"{field_lower} entry level"],
            domain_terms=[field_lower],
        )
    return DomainKeywords(
        retrieval_keywords=["policy", "international development", "public affairs"],
        domain_terms=["policy", "public affairs", "international"],
    )


# --- public API ---------------------------------------------------------------


def extract_domain_keywords(
    field: str,
    skills: list[str],
    experience: str,
    llm_ask=None,  # Callable[[str], str] | None
) -> DomainKeywords:
    """Extract domain-specific keywords from a candidate profile.

    Uses an LLM if ``llm_ask`` is provided; falls back to hardcoded mappings
    otherwise.  Never raises — a parse failure returns the fallback.
    """
    if llm_ask is None:
        log.info("domain_filter: no LLM configured, using fallback keywords for field=%s", field)
        return _fallback_keywords(field)

    prompt = _build_prompt(field, skills, experience)
    try:
        raw = llm_ask(prompt)
    except Exception:
        log.exception("domain_filter: LLM call failed, using fallback")
        return _fallback_keywords(field)

    result = _parse_response(raw)
    if not result.retrieval_keywords or not result.domain_terms:
        log.warning("domain_filter: LLM returned empty fields, using fallback")
        return _fallback_keywords(field)
    return result


def passes_domain_filter(
    job: Job,
    domain_terms: list[str],
    min_hits: int = 1,
) -> bool:
    """Whether a job posting contains at least ``min_hits`` domain terms.

    Multi-word terms (e.g. "public affairs") are matched as complete phrases
    to avoid false positives from generic single words like "international"
    matching unrelated contexts ("international team" at a tech company).
    Single-word terms use word-boundary matching for the same reason.
    """
    if not domain_terms:
        return True  # no filter → everything passes
    text = f"{job.title} {job.description}".lower()
    hits = 0
    for term in domain_terms:
        t = term.lower()
        if " " in t:
            # Multi-word: exact phrase match (substring is fine for compounds)
            if t in text:
                hits += 1
        else:
            # Single word: word-boundary match to avoid substring false positives
            # e.g. "policy" should match "policy brief" but not "policyholder"
            if re.search(r"\b" + re.escape(t) + r"\b", text):
                hits += 1
    return hits >= min_hits


def filter_by_domain(
    jobs: list[Job],
    domain_terms: list[str],
    min_hits: int = 1,
) -> list[Job]:
    """Batch filter: keep only jobs that pass the domain relevance gate."""
    if not domain_terms:
        return jobs
    return [j for j in jobs if passes_domain_filter(j, domain_terms, min_hits)]


# --- factory: build the keyword-LLM ask callable from settings ----------------


def build_keyword_llm_ask(settings=None):  # Settings | None -> Callable[[str], str] | None
    """Return an ``ask(prompt) -> str`` callable for the keyword LLM, or ``None``.

    Uses the ``keyword_llm_*`` settings (defaults to Mistral-small).  Returns
    ``None`` when no keyword LLM key is configured — callers should fall back
    to ``extract_domain_keywords(..., llm_ask=None)`` which uses hardcoded maps.
    """
    from job_agent.config import get_settings

    s = settings if settings is not None else get_settings()
    if not s.keyword_llm_api_key:
        return None

    from openai import OpenAI  # lazy — keeps import-safe offline

    client = OpenAI(api_key=s.keyword_llm_api_key, base_url=s.keyword_llm_base_url)
    model = s.keyword_llm_model

    def ask(prompt: str) -> str:
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=400,
        )
        return resp.choices[0].message.content or ""

    return ask
