"""Notifications (FR-16 e-mail, FR-17 in-app + push).

1. During a request, services call `notify_*`. That writes one `notification` row per recipient
   in the same transaction as the change (this row is what the VS Code extension polls).
2. After the response, `deliver` runs as a background task: it pushes to the recipient's private
   topic on our **self-hosted** ntfy server and sends an e-mail over SMTP, honouring each
   user's preferences. Failures are logged and stored as `failed`; they never affect the
   request that caused them.
"""

import json
import logging
import smtplib
import urllib.error
import urllib.request
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import (
    Bug,
    BugStatus,
    DeliveryStatus,
    Notification,
    NotificationKind,
    Project,
    ProjectMember,
    ProjectRole,
    User,
)

logger = logging.getLogger(__name__)
PENDING_KEY = "pending_notification_ids"


# --------------------------------------------------------------------------- transports
@dataclass(frozen=True)
class OutgoingMessage:
    to_email: str
    to_name: str
    topic: str
    title: str
    body: str
    priority: int  # ntfy priority 1..5
    tags: tuple[str, ...]


class PushSender(Protocol):
    def send(self, message: OutgoingMessage) -> None: ...


class EmailSender(Protocol):
    def send(self, message: OutgoingMessage) -> None: ...


class NtfyPushSender:
    def __init__(self, settings: Settings) -> None:
        self.url = settings.ntfy_publish_url.rstrip("/")
        self.token = settings.ntfy_publish_token
        self.timeout = settings.notification_timeout_seconds

    def send(self, message: OutgoingMessage) -> None:
        payload = {
            "topic": message.topic,
            "title": message.title,
            "message": message.body,
            "priority": message.priority,
            "tags": list(message.tags),
        }
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = urllib.request.Request(  # noqa: S310 (URL comes from deployment settings)
            self.url + "/", data=json.dumps(payload).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
            if response.status >= 300:
                raise RuntimeError(f"ntfy answered HTTP {response.status}")


class SmtpEmailSender:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send(self, message: OutgoingMessage) -> None:
        s = self.settings
        email = EmailMessage()
        email["From"] = s.smtp_from
        email["To"] = f"{message.to_name} <{message.to_email}>"
        email["Subject"] = message.title
        email.set_content(message.body)
        with smtplib.SMTP(s.smtp_host, s.smtp_port, timeout=s.notification_timeout_seconds) as smtp:
            if s.smtp_use_tls:
                smtp.starttls()
            if s.smtp_username:
                smtp.login(s.smtp_username, s.smtp_password)
            smtp.send_message(email)


@dataclass
class Transports:
    push: PushSender
    email: EmailSender

    @classmethod
    def from_settings(cls, settings: Settings) -> "Transports":
        return cls(push=NtfyPushSender(settings), email=SmtpEmailSender(settings))


def topic_for(user: User, settings: Settings) -> str:
    return f"{settings.ntfy_topic_prefix}-{user.ntfy_topic}"


# --------------------------------------------------------------------------- creation
def _queue(
    db: Session,
    recipients: Iterable[User | None],
    kind: NotificationKind,
    bug: Bug,
    title: str,
    message: str,
    exclude: User | None,
) -> list[Notification]:
    seen: set[int] = set()
    created = []
    for user in recipients:
        if user is None or not user.is_active or user.id in seen:
            continue
        if exclude is not None and user.id == exclude.id:
            continue  # nobody is notified about their own action
        seen.add(user.id)
        notification = Notification(
            user_id=user.id,
            bug_id=bug.id,
            kind=kind,
            title=title[:200],
            message=message,
            email_status=(
                DeliveryStatus.PENDING if user.email_notifications else DeliveryStatus.SKIPPED
            ),
            push_status=(
                DeliveryStatus.PENDING if user.push_notifications else DeliveryStatus.SKIPPED
            ),
        )
        db.add(notification)
        created.append(notification)
    db.flush()
    db.info.setdefault(PENDING_KEY, []).extend(n.id for n in created)
    return created


def _project_name(db: Session, bug: Bug) -> str:
    project = db.get(Project, bug.project_id)
    return project.name if project else f"project #{bug.project_id}"


def _footer(bug: Bug) -> str:
    return f"\n\nOpen it in VS Code with 'Bug Tracker: Open Bug' and enter #{bug.id}."


def notify_assigned(db: Session, bug: Bug, actor: User, assignee: User) -> None:
    title = f"[Bug #{bug.id}] Assigned to you: {bug.title}"
    body = (
        f"{actor.full_name} assigned bug #{bug.id} in {_project_name(db, bug)} to you.\n"
        f"Severity: {bug.severity.value}\nStatus: {bug.status.value}" + _footer(bug)
    )
    _queue(db, [assignee], NotificationKind.ASSIGNED, bug, title, body, exclude=actor)


def notify_status_changed(
    db: Session,
    bug: Bug,
    actor: User,
    old: BugStatus,
    new: BugStatus,
    skip_user_id: int | None = None,
) -> None:
    recipients = [
        db.get(User, user_id)
        for user_id in (bug.reporter_id, bug.assignee_id)
        if user_id is not None and user_id != skip_user_id
    ]
    title = f"[Bug #{bug.id}] {old.value} → {new.value}: {bug.title}"
    body = (
        f"{actor.full_name} moved bug #{bug.id} in {_project_name(db, bug)} "
        f"from {old.value} to {new.value}." + _footer(bug)
    )
    _queue(db, recipients, NotificationKind.STATUS_CHANGED, bug, title, body, exclude=actor)


def notify_critical(db: Session, bug: Bug, actor: User | None) -> None:
    managers = db.scalars(
        select(User)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .where(
            ProjectMember.project_id == bug.project_id,
            ProjectMember.role == ProjectRole.PROJECT_MANAGER,
        )
    ).all()
    recipients: list[User | None] = [*managers]
    if bug.assignee_id:
        recipients.append(db.get(User, bug.assignee_id))
    title = f"[Bug #{bug.id}] CRITICAL: {bug.title}"
    body = (
        f"Bug #{bug.id} in {_project_name(db, bug)} is now Critical "
        f"({'set by ' + actor.full_name if actor else 'predicted by the AI triage'})."
        + _footer(bug)
    )
    _queue(db, recipients, NotificationKind.CRITICAL_BUG, bug, title, body, exclude=actor)


def take_pending_ids(db: Session) -> list[int]:
    ids: list[int] = db.info.pop(PENDING_KEY, [])
    return ids


# --------------------------------------------------------------------------- delivery
_PRIORITY = {
    NotificationKind.CRITICAL_BUG: 5,
    NotificationKind.ASSIGNED: 4,
    NotificationKind.STATUS_CHANGED: 3,
}
_TAGS = {
    NotificationKind.CRITICAL_BUG: ("rotating_light", "bug"),
    NotificationKind.ASSIGNED: ("bug", "point_right"),
    NotificationKind.STATUS_CHANGED: ("bug",),
}


def deliver(
    session_factory: sessionmaker[Session],
    settings: Settings,
    transports: Transports,
    notification_ids: Sequence[int],
) -> None:
    """Background task: send pending push/e-mail deliveries and record the outcome."""
    if not notification_ids:
        return
    with session_factory() as db:
        rows = db.execute(
            select(Notification, User)
            .join(User, User.id == Notification.user_id)
            .where(Notification.id.in_(notification_ids))
        ).all()
        for notification, user in rows:
            message = OutgoingMessage(
                to_email=user.email,
                to_name=user.full_name,
                topic=topic_for(user, settings),
                title=notification.title,
                body=notification.message,
                priority=_PRIORITY[notification.kind],
                tags=_TAGS[notification.kind],
            )
            if notification.push_status == DeliveryStatus.PENDING:
                notification.push_status = _attempt("push", transports.push, message, notification)
            if notification.email_status == DeliveryStatus.PENDING:
                notification.email_status = _attempt(
                    "email", transports.email, message, notification
                )
        db.commit()


def _attempt(
    channel: str, sender: PushSender | EmailSender, message: OutgoingMessage, row: Notification
) -> DeliveryStatus:
    try:
        sender.send(message)
    except (OSError, smtplib.SMTPException, urllib.error.URLError, RuntimeError) as exc:
        logger.warning("Notification %s via %s failed: %s", row.id, channel, exc)
        return DeliveryStatus.FAILED
    return DeliveryStatus.SENT


# --------------------------------------------------------------------------- in-app API
def list_for_user(
    db: Session, user: User, unread_only: bool, page: int, page_size: int
) -> tuple[list[Notification], int]:
    query = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        query = query.where(Notification.is_read.is_(False))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    items = db.scalars(
        query.order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total


def unread_count(db: Session, user: User) -> int:
    return (
        db.scalar(
            select(func.count()).where(
                Notification.user_id == user.id, Notification.is_read.is_(False)
            )
        )
        or 0
    )


def mark_read(db: Session, user: User, notification_id: int | None) -> int:
    statement = update(Notification).where(
        Notification.user_id == user.id, Notification.is_read.is_(False)
    )
    if notification_id is not None:
        statement = statement.where(Notification.id == notification_id)
    result = db.execute(statement.values(is_read=True))
    db.commit()
    return int(result.rowcount)  # type: ignore[attr-defined]


def owns(db: Session, user: User, notification_id: int) -> bool:
    return (
        db.scalar(
            select(Notification.id).where(
                Notification.id == notification_id, Notification.user_id == user.id
            )
        )
        is not None
    )
