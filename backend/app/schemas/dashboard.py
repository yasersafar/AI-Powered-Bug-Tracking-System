from datetime import date

from pydantic import BaseModel, Field


class DayCount(BaseModel):
    """Bugs created and resolved on one day (dashboard)."""

    day: date
    created: int
    resolved: int


class ComponentCount(BaseModel):
    """Open bugs per component (dashboard)."""

    component: str
    open_bugs: int


class ProjectDashboard(BaseModel):
    """FR-15 project dashboard."""

    project_id: int
    total_bugs: int
    open_bugs: int = Field(description="Bugs in Open or InProgress.")
    open_critical: int
    by_status: dict[str, int]
    by_severity: dict[str, int]
    over_time: list[DayCount]
    average_resolution_hours: float | None = Field(
        description="Mean hours from submission to (latest) resolution, over resolved bugs."
    )
    top_components: list[ComponentCount]
    days: int
