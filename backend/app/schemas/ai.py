"""Request/response models of the triage endpoints (FR-10, FR-11, FR-12, FR-22, NFR-10)."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AiStatus, BugStatus, Severity
from app.schemas.common import MultiLine, SingleLine

DraftTitle = Annotated[SingleLine, Field(max_length=200, examples=["Crash when saving"])]
DraftDescription = Annotated[
    MultiLine,
    Field(max_length=20000, examples=["Saving a file larger than 2 MB closes the editor."]),
]
Component = Annotated[SingleLine, Field(min_length=1, max_length=80)]
StepName = Literal["duplicates", "severity", "assignment"]


class _Draft(BaseModel):
    """A report being written. Partial text is fine: this is called while the user types."""

    model_config = ConfigDict(extra="forbid")

    title: DraftTitle = ""
    description: DraftDescription = ""

    @model_validator(mode="after")
    def _some_text(self) -> "_Draft":
        if len((self.title + self.description).strip()) < 3:
            raise ValueError("title or description must contain at least 3 characters")
        return self


class DuplicateCheckRequest(_Draft):
    """Draft text to check for duplicates while the user types (FR-10)."""

    project_id: int
    exclude_bug_id: int | None = Field(
        default=None, description="When editing an existing bug, leave it out of the results."
    )


class SeverityRequest(_Draft):
    """Draft text to classify (FR-11)."""

    pass


class TriageRequest(_Draft):
    """Draft report for the full triage pipeline."""

    project_id: int
    components: list[Component] = Field(default_factory=list, max_length=10)


class AssignRequest(TriageRequest):
    """Run only the recommender. The shared state can be passed in explicitly."""

    severity: Literal[Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL] | None = (
        Field(default=None, description="Known severity; Critical filters out busy developers.")
    )
    duplicate_of_ids: list[int] = Field(
        default_factory=list,
        max_length=10,
        description="Bugs this report duplicates; their fixers get a boost.",
    )


class DuplicateMatch(BaseModel):
    """An earlier report of the same project that may be a duplicate."""

    bug_id: int
    title: str
    status: BugStatus
    score: float = Field(description="Hybrid similarity in [0, 1] (BM25 + MiniLM).")


class SeverityResult(BaseModel):
    """Predicted severity, its confidence and the probability of every class."""

    severity: Severity | None = Field(description="None when the step was degraded.")
    confidence: float | None
    probabilities: dict[str, float] = Field(default_factory=dict)


class DeveloperSuggestion(BaseModel):
    """A recommended developer with score and reason (FR-12, FR-22)."""

    developer_id: int
    name: str
    score: float
    reason: Literal["history match", "skill match", "new developer (cold start)"]
    alpha: float = Field(description="Weight of history vs profile: min(1, resolved / N).")
    history_score: float
    profile_score: float
    explored: bool = Field(description="Placed in slot 3 by cold-start exploration.")
    notes: list[str] = Field(default_factory=list)


class StepInfo(BaseModel):
    """Status and time of one triage step."""

    status: Literal["ok", "degraded", "skipped"]
    elapsed_ms: float
    detail: str | None = None


class TriageResponse(BaseModel):
    """Same shape for every /ai endpoint; parts that were not requested are empty."""

    ai_status: AiStatus = Field(description="`degraded` if any requested step failed.")
    notice: str | None = Field(description="Human-readable explanation when degraded.")
    duplicates: list[DuplicateMatch]
    is_likely_duplicate: bool
    severity: SeverityResult
    recommendations: list[DeveloperSuggestion]
    steps: dict[StepName, StepInfo]
    total_ms: float


class ModelVersion(BaseModel):
    """One row of `model_state`: a triage model and the artifact being served."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    status: str
    artifact: str | None
    sha256: str | None = Field(description="SHA-256 of the weight file being served.")
    size_bytes: int | None
    detail: str | None
    loaded_by: str
    loaded_at: datetime


class AiStatusResponse(BaseModel):
    """State of the in-process triage models and which artifacts are served."""

    enabled: bool = Field(description="The administrator switch `ai_enabled`.")
    state: Literal["disabled", "loading", "ready", "failed"]
    error: str | None
    models: dict[str, str]
    load_seconds: float | None
    indexed_reports: int
    served_models: list[ModelVersion] = Field(
        default_factory=list, description="Rows of `model_state`: which artifact is served."
    )
