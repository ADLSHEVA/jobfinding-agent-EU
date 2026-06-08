"""Matching — turn a stream of jobs into a ranked, candidate-facing shortlist.

Ranking combines visa feasibility (dominant tier) with CV↔job relevance, visa
signal, and language fit. Relevance defaults to offline lexical similarity; pass a
``SemanticSimilarity(embedder)`` to use a third-party embeddings provider instead
(DeepSeek has no embeddings endpoint). ``analyze_gap`` gives per-job LLM gap
analysis on demand.
"""

from job_agent.matching.domain_filter import (
    DomainKeywords,
    build_keyword_llm_ask,
    extract_domain_keywords,
    filter_by_domain,
    passes_domain_filter,
)
from job_agent.matching.embedders import (
    OpenAICompatibleEmbedder,
    build_embedder,
    default_similarity,
)
from job_agent.matching.gap import GapAnalysis, analyze_gap
from job_agent.matching.shortlist import RankedJob, content_score, shortlist
from job_agent.matching.similarity import (
    Embedder,
    SemanticSimilarity,
    cosine,
    lexical_similarity,
)

__all__ = [
    "DomainKeywords",
    "Embedder",
    "build_keyword_llm_ask",
    "GapAnalysis",
    "OpenAICompatibleEmbedder",
    "RankedJob",
    "SemanticSimilarity",
    "analyze_gap",
    "build_embedder",
    "content_score",
    "cosine",
    "default_similarity",
    "extract_domain_keywords",
    "filter_by_domain",
    "lexical_similarity",
    "passes_domain_filter",
    "shortlist",
]
