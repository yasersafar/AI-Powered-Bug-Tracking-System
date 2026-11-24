from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import AiStatus, BugStatus, CloseReason, Severity
from app.schemas.common import MultiLine, SingleLine, UserSummary

Title = Annotated[SingleLine, Field(min_length=5, max_length=200, examples=["Crash when saving"])]
Description = Annotated[
    MultiLine,
    Field(
        min_length=20,
        max_length=20000,
        examples=["Saving a file larger than 2 MB closes the editor without an error message."],
    ),
]
Steps = Annotated[MultiLine, Field(min_length=1, max_length=10000, examples=["1. Open a file"])]
Environment = Annotated[
    SingleLine, Field(min_length=1, max_length=500, examples=["VS Code 1.105, macOS 15"])
]
Component = Annotated[SingleLine, Field(min_length=1, max_length=80)]


def _dedupe_components(values: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for value in values:
        seen.setdefault(value, None)
    return list(seen)


class BugCreate(BaseModel):
    """FR-05 bug submission form."""

    model_config = ConfigDict(extra="forbid")

    project_id: int
    title: Title
    description: Description
    steps_to_reproduce: Steps
    environment: Environment
    components: list[Component] = Field(default_factory=list, max_length=10)

    _dedupe = field_validator("components")(_dedupe_components)


class BugUpdate(BaseModel):
    """Editable bug fields; only the fields sent are changed."""

    model_config = ConfigDict(extra="forbid")

    title: Title | None = None
    description: Description | None = None
    steps_to_reproduce: Steps | None = None
    environment: Environment | None = None
    components: list[Component] | None = Field(default=None, max_length=10)

    @field_validator("components")
    @classmethod
    def _components(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _dedupe_components(value)


class TransitionRequest(BaseModel):
    """FR-06: request a status change. Closing an Open bug needs a reason."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {"to_status": "Closed", "close_reason": "duplicate", "duplicate_of_id": 12}
            ]
        },
    )

    to_status: BugStatus
    close_reason: Literal[CloseReason.INVALID, CloseReason.DUPLICATE] | None = None
    duplicate_of_id: int | None = None

    @model_validator(mode="after")
    def _duplicate_needs_target(self) -> "TransitionRequest":
        if self.close_reason == CloseReason.DUPLICATE and self.duplicate_of_id is None:
            raise ValueError("duplicate_of_id is required when close_reason is 'duplicate'")
        if self.duplicate_of_id is not None and self.close_reason != CloseReason.DUPLICATE:
            raise ValueError("duplicate_of_id is only allowed with close_reason 'duplicate'")
        return self


class AssignRequest(BaseModel):
    """Assign the bug to a project developer (Project Manager)."""

    model_config = ConfigDict(extra="forbid", json_schema_extra={"examples": [{"assignee_id": 4}]})

    assignee_id: int


class SeverityOverrideRequest(BaseModel):
    """Severity chosen by a Developer or Project Manager (FR-11, audited)."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"severity": "Critical"}]}
    )

    severity: Literal[Severity.LOW, Severity.MEDIUM, Severity.HIGH, Severity.CRITICAL]


class BugListItem(BaseModel):
    """Bug summary used in lists and search results."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    status: BugStatus
    severity: Severity
    ai_status: AiStatus
    assignee: UserSummary | None
    reporter: UserSummary | None
    components: list[str]
    created_at: datetime
    updated_at: datetime


class BugRead(BugListItem):
    """Full bug with AI results and what the caller may do with it."""

    description: str
    steps_to_reproduce: str
    environment: str
    close_reason: CloseReason | None
    duplicate_of_id: int | None
    predicted_severity: Severity | None
    severity_confidence: float | None
    severity_overridden: bool
    duplicate_candidates: list[dict[str, Any]]
    recommended_developers: list[dict[str, Any]]
    ai_details: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-step triage status/timing and `notice`, a message to show when AI "
        "results are missing (NFR-10).",
    )
    resolved_at: datetime | None
    closed_at: datetime | None
    allowed_transitions: list[BugStatus] = Field(
        default_factory=list, description="Statuses the caller may move this bug to now."
    )
    can_override_severity: bool = False
    can_assign: bool = False
    can_edit: bool = False


BugSort = Literal["created_desc", "created_asc", "updated_desc", "severity_desc", "relevance"]
