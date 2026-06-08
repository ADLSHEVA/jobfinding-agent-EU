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

    @staticmethod
    def _cv_text(candidate: CandidateProfile) -> str:
        return (f"{candidate.field}. Skills: {', '.join(candidate.skills)}."
                f" Experience: {candidate.experience}")

    def __call__(self, candidate: CandidateProfile, job: Job) -> float:
        try:
            vectors = self._embedder.embed([self._cv_text(candidate),
                                            f"{job.title}. {job.description}"])
        except Exception:  # noqa: BLE001 - a transient embedding failure must not crash ranking
            return 0.0
        return max(0.0, cosine(vectors[0], vectors[1]))

    def score_all(self, candidate: CandidateProfile, jobs: list[Job]) -> list[float]:
        """Embed the CV once and all jobs in BATCHES — one API round per ~96 jobs instead
        of one per job. ``shortlist`` calls this when present, which is the difference
        between ~4 requests and several hundred for a Europe-wide result set."""
        if not jobs:
            return []
        job_texts = [f"{j.title}. {j.description}" for j in jobs]
        try:
            cv_vec = self._embedder.embed([self._cv_text(candidate)])[0]
            vecs: list[list[float]] = []
            for i in range(0, len(job_texts), 96):  # chunk to stay within provider limits
                vecs.extend(self._embedder.embed(job_texts[i:i + 96]))
        except Exception:  # noqa: BLE001 - embeddings down → caller falls back to lexical
            return [lexical_similarity(candidate, j) for j in jobs]
        return [max(0.0, cosine(cv_vec, v)) for v in vecs]
