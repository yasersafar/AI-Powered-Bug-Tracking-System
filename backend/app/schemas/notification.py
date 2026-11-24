from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import DeliveryStatus, NotificationKind


class NotificationRead(BaseModel):
    """An in-app notification (FR-17) with its e-mail and push delivery state."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    kind: NotificationKind
    bug_id: int | None
    title: str
    message: str
    is_read: bool
    email_status: DeliveryStatus
    push_status: DeliveryStatus
    created_at: datetime


class UnreadCount(BaseModel):
    """Number of unread notifications."""

    unread: int


class MarkedRead(BaseModel):
    """Number of notifications marked as read."""

    updated: int


class PushSubscription(BaseModel):
    """FR-17: where to subscribe (ntfy app / desktop / VS Code) to receive push alerts."""

    server_url: str = Field(description="Self-hosted ntfy server.")
    topic: str = Field(description="Private, unguessable topic for this user (read-only).")
    subscribe_url: str
