from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

from app.models.enums import ProjectRole
from app.schemas.common import MultiLine, SingleLine, UserSummary

ProjectName = Annotated[SingleLine, Field(min_length=2, max_length=120, examples=["Payments API"])]
ProjectDescription = Annotated[MultiLine, Field(max_length=5000)]


class ProjectCreate(BaseModel):
    """A new project (FR-18)."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName
    description: ProjectDescription = ""


class ProjectUpdate(BaseModel):
    """Rename or describe a project."""

    model_config = ConfigDict(extra="forbid")

    name: ProjectName | None = None
    description: ProjectDescription | None = None


class ProjectRead(BaseModel):
    """A project and the caller's role in it."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str
    is_archived: bool
    archived_at: datetime | None
    created_at: datetime
    my_role: ProjectRole | None = Field(
        default=None, description="Caller's role in this project (null for non-member admins)."
    )


class MemberAdd(BaseModel):
    """Identify the user by id or by e-mail (exactly one)."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"user_id": 5, "role": "Developer"}]}
    )

    user_id: int | None = None
    email: EmailStr | None = None
    role: ProjectRole

    @model_validator(mode="after")
    def _exactly_one_identifier(self) -> "MemberAdd":
        if (self.user_id is None) == (self.email is None):
            raise ValueError("provide exactly one of user_id or email")
        return self


class MemberUpdate(BaseModel):
    """Change a member's project role."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"role": "ProjectManager"}]}
    )

    role: ProjectRole


class MemberRead(BaseModel):
    """A project member and their project role (FR-19)."""

    model_config = ConfigDict(from_attributes=True)

    user: UserSummary
    role: ProjectRole
    joined_at: datetime
