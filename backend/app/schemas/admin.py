from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import Availability, ExperienceLevel
from app.schemas.common import SingleLine, UserSummary

Tag = Annotated[SingleLine, Field(min_length=1, max_length=60)]


def _normalize_tags(values: list[str] | None) -> list[str] | None:
    """Lower-case, de-duplicate and sort so matching is case-insensitive and diffs are stable."""
    if values is None:
        return None
    return sorted({v.strip().lower() for v in values if v.strip()})


class ProfileFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[Tag] | None = Field(default=None, max_length=30, examples=[["python", "sql"]])
    components: list[Tag] | None = Field(default=None, max_length=30, examples=[["payments"]])
    languages: list[Tag] | None = Field(default=None, max_length=15, examples=[["python"]])
    experience_level: ExperienceLevel | None = None
    availability: Availability | None = None
    max_workload: int | None = Field(default=None, ge=1, le=50)
    active: bool | None = None

    _norm = field_validator("skills", "components", "languages")(_normalize_tags)


class ProfileCreate(ProfileFields):
    """FR-20: an Administrator creates a profile for a Developer account."""

    user_id: int


class ProfileUpdate(ProfileFields):
    """Editable profile fields; only the fields sent are changed."""

    pass


class ProfileRead(BaseModel):
    """Developer profile used by the recommender (FR-20), with cold-start state (FR-22)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user: UserSummary
    skills: list[str]
    components: list[str]
    languages: list[str]
    experience_level: ExperienceLevel
    availability: Availability
    max_workload: int
    active: bool
    resolved_count: int
    is_cold_start: bool
    created_at: datetime
    updated_at: datetime


class DeveloperStats(BaseModel):
    """FR-21 per-developer tracking."""

    user: UserSummary
    profile_id: int | None
    active: bool | None
    is_cold_start: bool | None
    alpha: float | None = Field(
        description="History weight min(1, resolved/N) used by the cold-start blend (FR-22)."
    )
    bugs_resolved: int
    average_resolution_hours: float | None
    reassignment_count: int = Field(description="Times a bug was reassigned away from them.")
    current_workload: int = Field(description="Assigned bugs that are Open or InProgress.")
    max_workload: int | None


class SettingRead(BaseModel):
    """A runtime threshold with its allowed range and last change (NFR-14)."""

    key: str
    value: float
    default: float
    minimum: float
    maximum: float
    type: str
    unit: str
    description: str
    updated_at: datetime | None
    updated_by: UserSummary | None


class SettingsUpdate(BaseModel):
    """New values for runtime settings, by key; validated against their ranges."""

    model_config = ConfigDict(extra="forbid")

    values: dict[str, float | int] = Field(
        examples=[{"cold_start_threshold": 10, "exploration_rate": 0.1}]
    )
