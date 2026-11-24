"""Hybrid developer scoring with cold-start handling (FR-12, FR-22).

    score = alpha * history_score + (1 - alpha) * profile_score
    alpha = min(1, resolved_count / N)

* history_score: CNN-LSTM probability for the developer, rescaled so the best candidate is 1.
  Developers the history model does not know get alpha = 0 (no usable history).
* profile_score: cosine similarity between the bug's TF-IDF vector and the developer's
  skills/components/languages text, plus a small bonus when the developer is Available.
* Exploration: with probability epsilon, slot 3 is reserved for the best-scoring cold-start
  developer (resolved_count < N) if none is already in the top 3.
* Shared triage state (the novelty): a likely duplicate boosts developers who fixed the
  original bug; a Critical bug filters out unavailable developers and those at max workload.
"""

import random
from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

HISTORY_MATCH = "history match"
SKILL_MATCH = "skill match"
NEW_DEVELOPER = "new developer (cold start)"


@dataclass(frozen=True)
class Candidate:
    developer_id: int
    name: str
    resolved_count: int
    profile_text: str
    history_score: float | None = None  # raw model probability; None = unknown to the model
    availability: str = "Available"  # Available | Limited | Unavailable
    workload: int = 0
    max_workload: int = 5
    active: bool = True


@dataclass(frozen=True)
class Recommendation:
    developer_id: int
    name: str
    score: float
    alpha: float
    history_score: float
    profile_score: float
    reason: str
    explored: bool = False
    notes: tuple[str, ...] = field(default_factory=tuple)


def _reason(resolved_count: int, alpha: float, history: float, profile: float) -> str:
    """Short explanation shown in the UI (FR-12)."""
    if resolved_count == 0:
        return NEW_DEVELOPER
    if alpha > 0 and alpha * history >= (1 - alpha) * profile:
        return HISTORY_MATCH
    return SKILL_MATCH


def alpha_for(resolved_count: int, threshold: int) -> float:
    return min(1.0, resolved_count / threshold) if threshold > 0 else 1.0


def profile_scores(
    bug_text: str, candidates: Sequence[Candidate], availability_bonus: float
) -> list[float]:
    texts = [c.profile_text or "" for c in candidates]
    if not any(t.strip() for t in texts) or not bug_text.strip():
        similarities = np.zeros(len(candidates))
    else:
        vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 1), sublinear_tf=True)
        matrix = vectorizer.fit_transform([bug_text, *texts])
        similarities = cosine_similarity(matrix[0], matrix[1:]).ravel()
    return [
        float(min(1.0, s + (availability_bonus if c.availability == "Available" else 0.0)))
        for s, c in zip(similarities, candidates, strict=True)
    ]


def recommend(
    bug_text: str,
    candidates: Sequence[Candidate],
    *,
    threshold: int,
    epsilon: float,
    availability_bonus: float = 0.1,
    top_k: int = 3,
    severity: str | None = None,
    original_fixers: Sequence[int] = (),
    duplicate_boost: float = 0.2,
    rng: random.Random | None = None,
    normalize_history: bool = True,
) -> list[Recommendation]:
    """`normalize_history=False` when history scores are already on a 0-1 scale that is
    comparable with the profile cosine (e.g. similarity to the developer's resolved reports);
    by default they are rescaled so the best candidate is 1 (raw model probabilities)."""
    rng = rng or random.Random()  # noqa: S311 (exploration, not security)
    pool = [c for c in candidates if c.active]
    if severity == "Critical":
        # Shared state: a Critical bug needs someone who can start now.
        pool = [c for c in pool if c.availability != "Unavailable" and c.workload < c.max_workload]
    if not pool:
        return []

    known = [c.history_score for c in pool if c.history_score is not None]
    best_history = max(known) if normalize_history and known and max(known) > 0 else 1.0
    profiles = profile_scores(bug_text, pool, availability_bonus)
    fixers = set(original_fixers)

    scored: list[Recommendation] = []
    for candidate, profile in zip(pool, profiles, strict=True):
        if candidate.history_score is None:
            alpha, history = 0.0, 0.0
        else:
            alpha = alpha_for(candidate.resolved_count, threshold)
            history = candidate.history_score / best_history
        score = alpha * history + (1 - alpha) * profile
        notes: tuple[str, ...] = ()
        if candidate.developer_id in fixers:
            score += duplicate_boost
            notes = ("fixed the original of this likely duplicate",)
        reason = _reason(candidate.resolved_count, alpha, history, profile)
        scored.append(
            Recommendation(
                candidate.developer_id,
                candidate.name,
                round(score, 4),
                round(alpha, 3),
                round(history, 4),
                round(profile, 4),
                reason,
                notes=notes,
            )
        )

    scored.sort(key=lambda r: (-r.score, r.developer_id))
    top = scored[:top_k]
    resolved = {c.developer_id: c.resolved_count for c in pool}
    is_cold = {d: n < threshold for d, n in resolved.items()}
    if (
        top_k >= 3
        and len(scored) > top_k
        and rng.random() < epsilon
        and not any(is_cold[r.developer_id] for r in top)
    ):
        newcomer = next((r for r in scored[top_k:] if is_cold[r.developer_id]), None)
        if newcomer is not None:
            top[top_k - 1] = Recommendation(
                **{**newcomer.__dict__, "reason": NEW_DEVELOPER, "explored": True}
            )
    return top
