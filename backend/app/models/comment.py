from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Comment(Base):
    """Flat, chronological comments on a bug (FR-09)."""

    __tablename__ = "comment"
    __table_args__ = (Index("ix_comment_bug_created", "bug_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bug_id: Mapped[int] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"))
    author_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    author: Mapped["User | None"] = relationship()
