import re
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field

from app.core.security import BCRYPT_MAX_BYTES
from app.models.enums import UserRole
from app.schemas.common import SingleLine


def _password_policy(value: str) -> str:
    """FR-01: >= 8 chars with at least one uppercase letter, one digit and one special char."""
    problems = []
    if len(value) < 8:
        problems.append("at least 8 characters")
    if not re.search(r"[A-Z]", value):
        problems.append("an uppercase letter")
    if not re.search(r"\d", value):
        problems.append("a number")
    if not re.search(r"[^A-Za-z0-9]", value):
        problems.append("a special character")
    if problems:
        raise ValueError("password needs " + ", ".join(problems))
    if len(value.encode("utf-8")) > BCRYPT_MAX_BYTES:
        raise ValueError(f"password must be at most {BCRYPT_MAX_BYTES} bytes")
    return value


Password = Annotated[
    str, Field(max_length=72, examples=["Str0ng!Pass"]), AfterValidator(_password_policy)
]
FullName = Annotated[SingleLine, Field(min_length=1, max_length=120, examples=["Dana Developer"])]


class RegisterRequest(BaseModel):
    """Self-registration always creates a Reporter; an Administrator grants other roles."""

    model_config = ConfigDict(extra="forbid")

    email: EmailStr = Field(examples=["dana@example.com"])
    full_name: FullName
    password: Password


class UserRead(BaseModel):
    """A user account as seen by an Administrator."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: UserRole
    is_active: bool
    created_at: datetime


class UserMe(UserRead):
    """The logged-in user, including notification preferences and push topic."""

    email_notifications: bool
    push_notifications: bool
    ntfy_topic: str = Field(description="Private ntfy topic for push alerts (FR-17).")


class TokenResponse(BaseModel):
    """JWT access token (8-hour expiry, FR-02) and the logged-in user."""

    access_token: str
    token_type: str = "bearer"  # noqa: S105 (OAuth2 token type, not a secret)
    expires_in: int = Field(description="Seconds until the token expires (8 hours, FR-02).")
    user: UserMe


class UpdateMeRequest(BaseModel):
    """FR-04: users edit their own name and notification preferences."""

    model_config = ConfigDict(extra="forbid")

    full_name: FullName | None = None
    email_notifications: bool | None = None
    push_notifications: bool | None = None


class ChangePasswordRequest(BaseModel):
    """Change the own password; all other sessions are signed out."""

    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(max_length=200)
    new_password: Password


class AdminUserUpdate(BaseModel):
    """Administrator changes a user's global role or deactivates the account."""

    model_config = ConfigDict(
        extra="forbid", json_schema_extra={"examples": [{"role": "Developer", "is_active": True}]}
    )

    role: UserRole | None = None
    is_active: bool | None = None
