"""Runtime settings (NFR-14) and notifications (FR-16, FR-17)."""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enums import DeliveryStatus, NotificationKind


def _enum(enum_cls: type, name: str) -> Enum:
    return Enum(enum_cls, name=name, values_callable=lambda e: [m.value for m in e])


class SystemSetting(Base):
    """Administrator-tunable threshold. Read on every use, so changes apply without redeploy."""

    __tablename__ = "system_setting"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)
    updated_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id", ondelete="SET NULL"))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Notification(Base):
    __tablename__ = "notification"
    __table_args__ = (Index("ix_notification_user_unread", "user_id", "is_read", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    bug_id: Mapped[int | None] = mapped_column(ForeignKey("bug.id", ondelete="CASCADE"))
    kind: Mapped[NotificationKind] = mapped_column(_enum(NotificationKind, "notification_kind"))
    title: Mapped[str] = mapped_column(String(200))
    message: Mapped[str] = mapped_column(Text)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    email_status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus, "delivery_status"), default=DeliveryStatus.PENDING
    )
    push_status: Mapped[DeliveryStatus] = mapped_column(
        _enum(DeliveryStatus, "delivery_status"), default=DeliveryStatus.PENDING
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ModelState(Base):
    """Which version of each triage model the backend is serving (one row per model).

    Written when the models are loaded. The SHA-256 of the weight file identifies the
    exact artifact, so results, logs and the running system can be matched to each other.
    """

    __tablename__ = "model_state"

    name: Mapped[str] = mapped_column(String(60), primary_key=True)
    status: Mapped[str] = mapped_column(String(20))  # loaded | unavailable
    artifact: Mapped[str | None] = mapped_column(String(300))
    sha256: Mapped[str | None] = mapped_column(String(64))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    detail: Mapped[str | None] = mapped_column(Text)
    loaded_by: Mapped[str] = mapped_column(String(120))  # host:pid of the worker
    loaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
