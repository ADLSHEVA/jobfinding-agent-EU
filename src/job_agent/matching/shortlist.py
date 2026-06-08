"""Rank jobs for a candidate: visa feasibility first, then CV relevance.

Ranking is lexicographic: the feasibility tier dominates (a job the candidate
cannot legally take must never outrank one they can), and within a tier jobs are
ordered by a *content score* = CV↔job relevance + visa signal + language fit. Red
(no realistic route) is filtered out by default.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from job_agent.matching.similarity import lexical_similarity
from job_agent.models.candidate import CandidateProfile
from job_agent.models.job import Job, VisaSignal
from job_agent.visa import FeasibilityLevel, FeasibilityResult, assess

_LEVEL_RANK: dict[FeasibilityLevel, int] = {
    FeasibilityLevel.green: 2,
    FeasibilityLevel.yellow: 1,
    FeasibilityLevel.red: 0,
}
_SIGNAL_BONUS: dict[VisaSignal, float] = {
    VisaSignal.explicit_yes: 0.10,
    VisaSignal.likely: 0.05,
    VisaSignal.unknown: 0.0,
    VisaSignal.explicit_no: -0.15,
}
_SIMILARITY_WEIGHT = 0.5

# A relevance scorer maps (candidate, job) -> [0, 1]. Default is offline lexical.
Similarity = Callable[[CandidateProfile, Job], float]


@dataclass
class RankedJob:
    job: Job
    feasibility: FeasibilityResult
    similarity: float
    score: float  # within-tier content score


def _language_ok(candidate: CandidateProfile, job: Job) -> bool:
    if not job.languages_required:
        return True
    spoken = {lang.lower() for lang in candidate.languages}
    return bool(spoken & {lang.lower() for lang in job.languages_required})


def content_score(candidate: CandidateProfile, job: Job, similarity_val: float) -> float:
    """Within-tier score in [0, 1]: relevance (weighted) + signal + language fit."""
    score = _SIMILARITY_WEIGHT * similarity_val
    score += _SIGNAL_BONUS.get(job.visa_signal, 0.0)
    score += 0.05 if _language_ok(candidate, job) else -0.10
    return round(max(0.0, min(1.0, score)), 3)


def shortlist(
    candidate: CandidateProfile,
    jobs: list[Job],
    *,
    include_red: bool = False,
    similarity: Similarity = lexical_similarity,
) -> list[RankedJob]:
    """Assess + score every job, then sort by (feasibility tier, content score)."""
    # Batch-embed up front when the scorer supports it (semantic): one API round per ~96
    # jobs instead of one call per job — the difference between seconds and minutes on a
    # Europe-wide result set. Lexical scoring is local, so the per-job path is fine.
    score_all = getattr(similarity, "score_all", None)
    sims = score_all(candidate, jobs) if callable(score_all) else None

    ranked: list[RankedJob] = []
    for i, job in enumerate(jobs):
        feasibility = assess(candidate, job)
        if feasibility.level is FeasibilityLevel.red and not include_red:
            continue
        sim = sims[i] if sims is not None else similarity(candidate, job)
        ranked.append(RankedJob(job, feasibility, round(sim, 3), content_score(candidate, job, sim)))
    ranked.sort(key=lambda r: (_LEVEL_RANK[r.feasibility.level], r.score), reverse=True)
    return ranked
