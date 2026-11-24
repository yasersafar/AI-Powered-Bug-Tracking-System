"""Shared triage state (section 5.2 of the design): one object flows through all three steps.

    TriageContext(text, project_id, components)
       -> DuplicateDetector    adds duplicate_candidates, is_likely_duplicate (+ query embedding)
       -> SeverityClassifier   adds severity, confidence
       -> DeveloperRecommender reads severity + duplicate info:
              likely duplicate -> boost developers who fixed the original bug
              Critical         -> drop developers who are unavailable or at max workload
       -> TriageResult

Each step reports its own status and time, so a failing or slow step is marked `degraded`
while the others still run (NFR-10).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

import numpy as np
from numpy.typing import NDArray

from ml.assignment.cold_start import Recommendation
from ml.common.text import clean_text, report_text
from ml.duplicate.detector import DuplicateCandidate

# The duplicate index stores embeddings of the first 1,000 characters (same as the evaluation).
EMBED_CHARS = 1000

DUPLICATES = "duplicates"
SEVERITY = "severity"
ASSIGNMENT = "assignment"
ALL_STEPS_ORDER = (DUPLICATES, SEVERITY, ASSIGNMENT)


class StepStatus(StrEnum):
    OK = "ok"
    DEGRADED = "degraded"  # failed, timed out or model unavailable
    SKIPPED = "skipped"  # not requested


@dataclass(frozen=True)
class StepReport:
    status: StepStatus
    elapsed_ms: float
    detail: str | None = None


@dataclass(frozen=True)
class TriageSettings:
    """Runtime thresholds (NFR-14), read from the admin settings for every request."""

    duplicate_min_score: float = 0.5
    duplicate_likely_threshold: float = 0.8
    duplicate_top_k: int = 3
    cold_start_threshold: int = 10
    exploration_rate: float = 0.1
    availability_bonus: float = 0.1
    duplicate_timeout_ms: int = 1200
    severity_timeout_ms: int = 1200
    assignment_timeout_ms: int = 2500
    recommendation_top_k: int = 3


@dataclass(frozen=True)
class DeveloperInfo:
    """A candidate assignee as the recommender sees it (built from the database)."""

    developer_id: int
    name: str
    resolved_count: int
    profile_text: str
    resolved_bug_ids: tuple[int, ...] = ()
    availability: str = "Available"
    workload: int = 0
    max_workload: int = 5
    active: bool = True


@dataclass
class TriageContext:
    title: str
    description: str
    project_id: int
    components: Sequence[str] = ()
    settings: TriageSettings = field(default_factory=TriageSettings)
    developers: Sequence[DeveloperInfo] = ()
    exclude_bug_ids: frozenset[int] = frozenset()

    # Written by the duplicate step
    query_vector: NDArray[np.float32] | None = None
    duplicate_candidates: list[DuplicateCandidate] = field(default_factory=list)
    is_likely_duplicate: bool = False
    # Written by the severity step
    severity: str | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    # Written by the assignment step
    recommendations: list[Recommendation] = field(default_factory=list)
    original_fixers: list[int] = field(default_factory=list)

    steps: dict[str, StepReport] = field(default_factory=dict)

    @property
    def text(self) -> str:
        """Model input: cleaned title + description (identical to training)."""
        return report_text(self.title, self.description)

    @property
    def embed_text(self) -> str:
        return clean_text(self.text, EMBED_CHARS)

    @property
    def assignment_text(self) -> str:
        """Report text plus component tokens, the CNN-LSTM input format."""
        tokens = " ".join(f"component_{c.lower().replace(' ', '_')}" for c in self.components)
        return f"{tokens} {self.text}".strip()

    @property
    def likely_originals(self) -> list[int]:
        threshold = self.settings.duplicate_likely_threshold
        return [c.bug_id for c in self.duplicate_candidates if c.score >= threshold]


@dataclass(frozen=True)
class TriageResult:
    duplicate_candidates: list[DuplicateCandidate]
    is_likely_duplicate: bool
    severity: str | None
    confidence: float | None
    probabilities: dict[str, float]
    recommendations: list[Recommendation]
    steps: dict[str, StepReport]
    total_ms: float
    query_vector: NDArray[np.float32] | None = None

    @property
    def ok(self) -> bool:
        return all(s.status != StepStatus.DEGRADED for s in self.steps.values())

    @classmethod
    def from_context(cls, ctx: TriageContext, total_ms: float) -> "TriageResult":
        return cls(
            duplicate_candidates=list(ctx.duplicate_candidates),
            is_likely_duplicate=ctx.is_likely_duplicate,
            severity=ctx.severity,
            confidence=ctx.confidence,
            probabilities=dict(ctx.probabilities),
            recommendations=list(ctx.recommendations),
            steps=dict(ctx.steps),
            total_ms=round(total_ms, 2),
            query_vector=ctx.query_vector,
        )
