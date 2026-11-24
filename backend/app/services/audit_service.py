"""Audit trail writer (FR-08, FR-19), called inside the same transaction as the change."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import AuditLog, User


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        return ", ".join(str(v) for v in value)
    return str(value)


def record(
    db: Session,
    actor: User | None,
    action: str,
    *,
    bug_id: int | None = None,
    project_id: int | None = None,
    target_user_id: int | None = None,
    profile_id: int | None = None,
    field: str | None = None,
    old: Any = None,
    new: Any = None,
) -> AuditLog:
    entry = AuditLog(
        actor_id=actor.id if actor else None,
        action=action,
        field=field,
        old_value=_text(old),
        new_value=_text(new),
        bug_id=bug_id,
        project_id=project_id,
        target_user_id=target_user_id,
        profile_id=profile_id,
    )
    db.add(entry)
    return entry


def user_label(user: User | None) -> str | None:
    return None if user is None else f"{user.full_name} (#{user.id})"


def bug_history(db: Session, bug_id: int) -> Sequence[AuditLog]:
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.bug_id == bug_id)
        .options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()


def project_history(db: Session, project_id: int) -> Sequence[AuditLog]:
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.project_id == project_id)
        .options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()


def user_history(db: Session, user_id: int) -> Sequence[AuditLog]:
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.target_user_id == user_id)
        .options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()


def profile_history(db: Session, profile_id: int) -> Sequence[AuditLog]:
    return db.scalars(
        select(AuditLog)
        .where(AuditLog.profile_id == profile_id)
        .options(selectinload(AuditLog.actor))
        .order_by(AuditLog.created_at, AuditLog.id)
    ).all()
