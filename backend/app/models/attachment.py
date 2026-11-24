from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class Attachment(Base):
    """File attached to a bug (FR-14). Stored on disk under a random name, never the user's."""

    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    bug_id: Mapped[int] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"), index=True)
    uploader_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    original_filename: Mapped[str] = mapped_column(String(255))
    storage_key: Mapped[str] = mapped_column(String(64), unique=True)
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    uploader: Mapped["User | None"] = relationship()
