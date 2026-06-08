"""CV ↔ job relevance scoring.

DeepSeek exposes no embeddings endpoint (verified: 404), so the default scorer is
**lexical** — set-cosine over tokens, fully offline and free. Semantic scoring is
available behind the ``Embedder`` seam: plug in any third-party embeddings provider
(OpenAI, Voyage, Cohere, a local model) and pass ``SemanticSimilarity(embedder)``
as the ``similarity`` argument to ``shortlist``.
"""

from __future__ import annotations

import math
import re
from typing import Protocol

from job_agent.models.candidate import CandidateProfile
from job_agent.models.job import Job

_TOKEN = re.compile(r"[a-zA-Zäöüßéèçàłńśźżáčďě]{3,}", re.UNICODE)
_STOP = {"and", "the", "for", "with", "you", "our", "are", "will", "der", "die", "und",
         "les", "des", "une", "your", "job", "role", "team", "work"}


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN.findall(text or "")} - _STOP


def _candidate_terms(candidate: CandidateProfile) -> set[str]:
    # Tokenise multi-word skills too ("policy analysis" -> {policy, analysis}) so they
    # can overlap with the word-tokenised job text.
    terms: set[str] = set()
    for skill in candidate.skills:
        terms |= _tokens(skill)
    terms |= _tokens(candidate.field)
    terms |= _tokens(candidate.experience)  # past internships/roles widen the match
    return terms


def lexical_similarity(candidate: CandidateProfile, job: Job) -> float:
    """Set-cosine of candidate skills/field against the job title + description, in [0, 1]."""
    cand = _candidate_terms(candidate)
    posting = _tokens(f"{job.title} {job.description}")
    if not cand or not posting:
        return 0.0
    overlap = len(cand & posting)
    return overlap / math.sqrt(len(cand) * len(posting))


class Embedder(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class SemanticSimilarity:
    """Embedding-backed relevance. Pass as ``similarity`` to ``shortlist``."""

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder

    def __call__(self, candidate: CandidateProfile, job: Job) -> float:
        cv_text = (f"{candidate.field}. Skills: {', '.join(candidate.skills)}."
                   f" Experience: {candidate.experience}")
        job_text = f"{job.title}. {job.description}"
        try:
            vectors = self._embedder.embed([cv_text, job_text])
        except Exception:  # noqa: BLE001 - a transient embedding failure must not crash ranking
            return 0.0
        return max(0.0, cosine(vectors[0], vectors[1]))
