import secrets
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import UserRole

if TYPE_CHECKING:
    from app.models.project import ProjectMember


def _new_ntfy_topic_suffix() -> str:
    # Unguessable per-user topic for self-hosted ntfy (FR-17).
    return secrets.token_urlsafe(18)


class User(Base):
    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda e: [m.value for m in e]),
        default=UserRole.REPORTER,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    email_notifications: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    push_notifications: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    ntfy_topic: Mapped[str] = mapped_column(String(64), unique=True, default=_new_ntfy_topic_suffix)
    # Embedded in every JWT ("ver"); bumping it revokes all tokens issued so far.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    memberships: Mapped[list["ProjectMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
