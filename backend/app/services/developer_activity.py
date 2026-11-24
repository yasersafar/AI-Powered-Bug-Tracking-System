"""Keeps assignment periods, resolution history and profile counters in step with bug events.

Called by bug_service inside the same transaction as the status/assignee change, so the
history used by FR-21 statistics and FR-22 cold-start logic can never disagree with the bugs.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import (
    AssignmentEnd,
    Bug,
    BugAssignment,
    DeveloperProfile,
    ResolutionHistory,
)
from app.services import settings_service


def _open_assignment(db: Session, bug_id: int) -> BugAssignment | None:
    return db.scalar(
        select(BugAssignment).where(
            BugAssignment.bug_id == bug_id, BugAssignment.ended_at.is_(None)
        )
    )


def on_assigned(db: Session, bug: Bug, developer_id: int, assigned_by_id: int | None) -> None:
    current = _open_assignment(db, bug.id)
    now = datetime.now(UTC)
    if current is not None:
        current.ended_at = now
        current.ended_reason = AssignmentEnd.REASSIGNED
        db.flush()  # the partial unique index allows only one open assignment per bug
    db.add(
        BugAssignment(
            bug_id=bug.id, developer_id=developer_id, assigned_by_id=assigned_by_id, assigned_at=now
        )
    )


def on_resolved(db: Session, bug: Bug, resolved_at: datetime) -> None:
    if bug.assignee_id is None:
        return
    assignment = _open_assignment(db, bug.id)
    started = assignment.assigned_at if assignment is not None else bug.created_at
    hours = max(0.0, (resolved_at - started).total_seconds() / 3600)
    db.add(
        ResolutionHistory(
            bug_id=bug.id,
            developer_id=bug.assignee_id,
            project_id=bug.project_id,
            severity=bug.severity,
            components=list(bug.components),
            assigned_at=started,
            resolved_at=resolved_at,
            resolution_hours=round(hours, 3),
        )
    )
    _change_resolved_count(db, bug.assignee_id, +1)


def on_reopened(db: Session, bug: Bug) -> None:
    latest = db.scalar(
        select(ResolutionHistory)
        .where(ResolutionHistory.bug_id == bug.id, ResolutionHistory.reopened.is_(False))
        .order_by(ResolutionHistory.resolved_at.desc())
        .limit(1)
    )
    if latest is None:
        return
    latest.reopened = True
    _change_resolved_count(db, latest.developer_id, -1)


def on_closed(db: Session, bug: Bug) -> None:
    current = _open_assignment(db, bug.id)
    if current is not None:
        current.ended_at = datetime.now(UTC)
        current.ended_reason = AssignmentEnd.CLOSED


def resolved_count(db: Session, developer_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).where(
                ResolutionHistory.developer_id == developer_id,
                ResolutionHistory.reopened.is_(False),
            )
        )
        or 0
    )


def _change_resolved_count(db: Session, developer_id: int, delta: int) -> None:
    profile = db.scalar(select(DeveloperProfile).where(DeveloperProfile.user_id == developer_id))
    if profile is None:
        return
    threshold = int(settings_service.get_value(db, "cold_start_threshold"))
    profile.resolved_count = max(0, profile.resolved_count + delta)
    profile.is_cold_start = profile.resolved_count < threshold


def refresh_cold_start_flags(db: Session, threshold: int) -> None:
    """FR-22: a developer leaves cold-start when resolved_count >= N (and re-enters if N rises)."""
    db.execute(
        update(DeveloperProfile).values(is_cold_start=DeveloperProfile.resolved_count < threshold)
    )
