from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import ProjectRole

if TYPE_CHECKING:
    from app.models.user import User


class Project(Base):
    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    members: Mapped[list["ProjectMember"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectMember(Base):
    __tablename__ = "project_member"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), index=True)
    role: Mapped[ProjectRole] = mapped_column(
        Enum(ProjectRole, name="project_role", values_callable=lambda e: [m.value for m in e])
    )
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    project: Mapped[Project] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="memberships")
