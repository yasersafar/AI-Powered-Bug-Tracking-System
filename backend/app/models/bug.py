from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enums import AiStatus, BugStatus, CloseReason, Severity

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.user import User


def _pg_enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class BugEmbedding(Base):
    """Cached sentence embedding of a report, so the duplicate index survives restarts."""

    __tablename__ = "bug_embedding"

    bug_id: Mapped[int] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"), primary_key=True)
    model: Mapped[str] = mapped_column(String(100))
    dimension: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Bug(Base):
    __tablename__ = "bug"
    __table_args__ = (
        Index("ix_bug_search_vector", "search_vector", postgresql_using="gin"),
        CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id <> id", name="not_self_duplicate"
        ),
        CheckConstraint(
            "severity_confidence IS NULL OR severity_confidence BETWEEN 0 AND 1",
            name="confidence_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("project.id", ondelete="CASCADE"), index=True
    )
    reporter_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    assignee_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="SET NULL"), index=True
    )

    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    steps_to_reproduce: Mapped[str] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(String(500))
    components: Mapped[list[str]] = mapped_column(
        ARRAY(String(80)), default=list, server_default="{}"
    )

    status: Mapped[BugStatus] = mapped_column(
        _pg_enum(BugStatus, "bug_status"), default=BugStatus.OPEN, index=True
    )
    severity: Mapped[Severity] = mapped_column(
        _pg_enum(Severity, "severity"), default=Severity.UNCLASSIFIED, index=True
    )
    close_reason: Mapped[CloseReason | None] = mapped_column(_pg_enum(CloseReason, "close_reason"))
    duplicate_of_id: Mapped[int | None] = mapped_column(ForeignKey("bug.id", ondelete="SET NULL"))

    # AI outputs (FR-10..FR-12). predicted_* keeps the model's answer even after an override.
    predicted_severity: Mapped[Severity | None] = mapped_column(
        _pg_enum(Severity, "severity"), nullable=True
    )
    severity_confidence: Mapped[float | None] = mapped_column(Float)
    severity_overridden: Mapped[bool] = mapped_column(default=False, server_default="false")
    duplicate_candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    recommended_developers: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list, server_default="[]"
    )
    ai_status: Mapped[AiStatus] = mapped_column(
        _pg_enum(AiStatus, "ai_status"), default=AiStatus.DEGRADED
    )
    # Per-step status and timing of the triage run, plus the notice shown when AI was degraded.
    ai_details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # FR-07: full-text search over title + description, kept up to date by PostgreSQL.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
            "setweight(to_tsvector('english', coalesce(description, '')), 'B')",
            persisted=True,
        ),
        deferred=True,
    )

    project: Mapped["Project"] = relationship()
    reporter: Mapped["User | None"] = relationship(foreign_keys=[reporter_id])
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_id])
    duplicate_of: Mapped["Bug | None"] = relationship(remote_side=[id])
