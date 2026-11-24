"""Developer profiles (FR-20), assignment and resolution history (FR-21, FR-22)."""

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AssignmentEnd, Availability, ExperienceLevel, Severity

if TYPE_CHECKING:
    from app.models.user import User


def _enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class DeveloperProfile(Base):
    """Admin-managed profile used by the assignment recommender and its cold-start logic."""

    __tablename__ = "developer_profile"
    __table_args__ = (
        CheckConstraint("max_workload >= 1", name="max_workload_positive"),
        CheckConstraint("resolved_count >= 0", name="resolved_count_non_negative"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"), unique=True)
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(String(40)), default=list, server_default="{}"
    )
    experience_level: Mapped[ExperienceLevel] = mapped_column(
        _enum(ExperienceLevel, "experience_level"), default=ExperienceLevel.MID
    )
    availability: Mapped[Availability] = mapped_column(
        _enum(Availability, "availability"), default=Availability.AVAILABLE
    )
    max_workload: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    resolved_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_cold_start: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship()
    skill_rows: Mapped[list["ProfileSkill"]] = relationship(
        cascade="all, delete-orphan", order_by="ProfileSkill.skill"
    )
    component_rows: Mapped[list["ProfileComponent"]] = relationship(
        cascade="all, delete-orphan", order_by="ProfileComponent.component"
    )

    @property
    def skills(self) -> list[str]:
        return [row.skill for row in self.skill_rows]

    @property
    def components(self) -> list[str]:
        return [row.component for row in self.component_rows]


class ProfileSkill(Base):
    __tablename__ = "profile_skill"
    __table_args__ = (UniqueConstraint("profile_id", "skill", name="uq_profile_skill"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("developer_profile.id", ondelete="CASCADE"), index=True
    )
    skill: Mapped[str] = mapped_column(String(60))


class ProfileComponent(Base):
    __tablename__ = "profile_component"
    __table_args__ = (UniqueConstraint("profile_id", "component", name="uq_profile_component"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("developer_profile.id", ondelete="CASCADE"), index=True
    )
    component: Mapped[str] = mapped_column(String(80))


class BugAssignment(Base):
    """One row per assignment period; feeds reassignment counts (FR-21)."""

    __tablename__ = "bug_assignment"
    __table_args__ = (
        Index("ix_bug_assignment_developer", "developer_id", "ended_reason"),
        Index(
            "uq_bug_assignment_one_open",
            "bug_id",
            unique=True,
            postgresql_where="ended_at IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bug_id: Mapped[int] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"), index=True)
    developer_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    assigned_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_reason: Mapped[AssignmentEnd | None] = mapped_column(
        _enum(AssignmentEnd, "assignment_end")
    )


class ResolutionHistory(Base):
    """A bug resolved by a developer. Reopened resolutions are kept but flagged (FR-21, FR-22)."""

    __tablename__ = "resolution_history"
    __table_args__ = (Index("ix_resolution_history_developer", "developer_id", "reopened"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bug_id: Mapped[int] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"), index=True)
    developer_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    project_id: Mapped[int] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    severity: Mapped[Severity] = mapped_column(_enum(Severity, "severity"))
    components: Mapped[list[str]] = mapped_column(ARRAY(String(80)), server_default="{}")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    resolution_hours: Mapped[float] = mapped_column(Float)
    reopened: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
