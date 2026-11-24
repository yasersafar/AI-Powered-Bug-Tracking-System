from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class AuditLog(Base):
    """Append-only audit trail (FR-08, FR-19). Written by the service layer, never by triggers.

    Exactly one target column is set per row: a bug, a project (membership / project
    changes), a user account (role / activation changes made by an Administrator) or a
    developer profile (FR-20).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(bug_id, project_id, target_user_id, profile_id) = 1",
            name="exactly_one_target",
        ),
        Index("ix_audit_log_bug_created", "bug_id", "created_at"),
        Index("ix_audit_log_project_created", "project_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40))
    field: Mapped[str | None] = mapped_column(String(60))
    old_value: Mapped[str | None] = mapped_column(Text)
    new_value: Mapped[str | None] = mapped_column(Text)
    bug_id: Mapped[int | None] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"))
    project_id: Mapped[int | None] = mapped_column(ForeignKey("project.id", ondelete="CASCADE"))
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), index=True
    )
    profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("developer_profile.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id])
