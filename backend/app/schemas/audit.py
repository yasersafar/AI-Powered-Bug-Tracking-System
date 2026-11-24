from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import UserSummary


class AuditEntryRead(BaseModel):
    """One audit-trail entry: who changed what, when (UTC), old and new value (FR-08)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    action: str
    field: str | None
    old_value: str | None
    new_value: str | None
    actor: UserSummary | None
    bug_id: int | None
    project_id: int | None
    target_user_id: int | None
    profile_id: int | None
    created_at: datetime
