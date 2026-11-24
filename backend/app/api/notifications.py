"""In-app notifications polled by the VS Code extension and push subscription info (FR-17)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.deps import AppSettings, CurrentUser, DbSession
from app.schemas.common import Page
from app.schemas.notification import MarkedRead, NotificationRead, PushSubscription, UnreadCount
from app.services import notification_service
from app.services.access import not_found

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=Page[NotificationRead], summary="My notifications, newest first")
def list_notifications(
    user: CurrentUser,
    db: DbSession,
    unread_only: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[NotificationRead]:
    items, total = notification_service.list_for_user(db, user, unread_only, page, page_size)
    return Page(
        items=[NotificationRead.model_validate(n) for n in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/unread-count", response_model=UnreadCount, summary="Number of unread notifications")
def unread(user: CurrentUser, db: DbSession) -> UnreadCount:
    return UnreadCount(unread=notification_service.unread_count(db, user))


@router.post("/{notification_id}/read", response_model=MarkedRead, summary="Mark one as read")
def mark_one(notification_id: int, user: CurrentUser, db: DbSession) -> MarkedRead:
    updated = notification_service.mark_read(db, user, notification_id)
    if updated == 0 and not notification_service.owns(db, user, notification_id):
        raise not_found("Notification")
    return MarkedRead(updated=updated)


@router.post("/read-all", response_model=MarkedRead, summary="Mark all as read")
def mark_all(user: CurrentUser, db: DbSession) -> MarkedRead:
    return MarkedRead(updated=notification_service.mark_read(db, user, None))


@router.get(
    "/subscription",
    response_model=PushSubscription,
    summary="My private ntfy topic for push alerts",
)
def subscription(user: CurrentUser, settings: AppSettings) -> PushSubscription:
    topic = notification_service.topic_for(user, settings)
    base = settings.ntfy_base_url.rstrip("/")
    return PushSubscription(server_url=base, topic=topic, subscribe_url=f"{base}/{topic}")
