"""Developer tracking (FR-21) and the project dashboard (FR-15)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import Date, cast, func, select
from sqlalchemy.orm import Session

from app.models import (
    AssignmentEnd,
    Bug,
    BugAssignment,
    BugStatus,
    DeveloperProfile,
    ResolutionHistory,
    Severity,
    User,
)
from app.schemas.admin import DeveloperStats
from app.schemas.common import UserSummary
from app.schemas.dashboard import ComponentCount, DayCount, ProjectDashboard
from app.services import settings_service

ACTIVE = (BugStatus.OPEN, BugStatus.IN_PROGRESS)


def workload(db: Session, developer_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).where(Bug.assignee_id == developer_id, Bug.status.in_(ACTIVE))
        )
        or 0
    )


def developer_stats(db: Session, user: User) -> DeveloperStats:
    resolved, avg_hours = db.execute(
        select(func.count(), func.avg(ResolutionHistory.resolution_hours)).where(
            ResolutionHistory.developer_id == user.id, ResolutionHistory.reopened.is_(False)
        )
    ).one()
    reassigned = (
        db.scalar(
            select(func.count()).where(
                BugAssignment.developer_id == user.id,
                BugAssignment.ended_reason == AssignmentEnd.REASSIGNED,
            )
        )
        or 0
    )
    profile = db.scalar(select(DeveloperProfile).where(DeveloperProfile.user_id == user.id))
    threshold = settings_service.get_value(db, "cold_start_threshold")
    return DeveloperStats(
        user=UserSummary.model_validate(user),
        profile_id=profile.id if profile else None,
        active=profile.active if profile else None,
        is_cold_start=profile.is_cold_start if profile else None,
        alpha=round(min(1.0, profile.resolved_count / threshold), 3) if profile else None,
        bugs_resolved=int(resolved),
        average_resolution_hours=round(float(avg_hours), 2) if avg_hours is not None else None,
        reassignment_count=int(reassigned),
        current_workload=workload(db, user.id),
        max_workload=profile.max_workload if profile else None,
    )


def all_developer_stats(db: Session) -> list[DeveloperStats]:
    """Every user with a profile or any assignment history."""
    ids = set(db.scalars(select(DeveloperProfile.user_id))) | set(
        db.scalars(select(BugAssignment.developer_id).distinct())
    )
    users = db.scalars(select(User).where(User.id.in_(ids)).order_by(User.full_name)).all()
    return [developer_stats(db, u) for u in users]


def project_dashboard(db: Session, project_id: int, days: int) -> ProjectDashboard:
    in_project = Bug.project_id == project_id
    by_status = {s.value: 0 for s in BugStatus}
    for status_value, count in db.execute(
        select(Bug.status, func.count()).where(in_project).group_by(Bug.status)
    ):
        by_status[status_value.value] = count
    by_severity = {s.value: 0 for s in Severity}
    for severity_value, count in db.execute(
        select(Bug.severity, func.count()).where(in_project).group_by(Bug.severity)
    ):
        by_severity[severity_value.value] = count

    today = datetime.now(UTC).date()
    start = today - timedelta(days=days - 1)
    start_ts = datetime.combine(start, datetime.min.time(), tzinfo=UTC)
    created_day = cast(func.timezone("UTC", Bug.created_at), Date)
    resolved_day = cast(func.timezone("UTC", Bug.resolved_at), Date)
    created = dict(
        db.execute(
            select(created_day, func.count())
            .where(in_project, Bug.created_at >= start_ts)
            .group_by(created_day)
        ).all()
    )
    resolved = dict(
        db.execute(
            select(resolved_day, func.count())
            .where(in_project, Bug.resolved_at >= start_ts)
            .group_by(resolved_day)
        ).all()
    )
    series = [
        DayCount(day=d, created=created.get(d, 0), resolved=resolved.get(d, 0))
        for d in (start + timedelta(days=i) for i in range(days))
    ]

    avg_seconds = db.scalar(
        select(func.avg(func.extract("epoch", Bug.resolved_at - Bug.created_at))).where(
            in_project, Bug.resolved_at.is_not(None)
        )
    )
    component = func.unnest(Bug.components).label("component")
    component_rows = db.execute(
        select(component, func.count())
        .where(in_project, Bug.status.in_(ACTIVE))
        .group_by(component)
        .order_by(func.count().desc(), component)
        .limit(5)
    ).all()
    open_bugs = by_status[BugStatus.OPEN.value] + by_status[BugStatus.IN_PROGRESS.value]
    open_critical = (
        db.scalar(
            select(func.count()).where(
                in_project, Bug.status.in_(ACTIVE), Bug.severity == Severity.CRITICAL
            )
        )
        or 0
    )
    return ProjectDashboard(
        project_id=project_id,
        total_bugs=sum(by_status.values()),
        open_bugs=open_bugs,
        open_critical=open_critical,
        by_status=by_status,
        by_severity=by_severity,
        over_time=series,
        average_resolution_hours=(
            round(float(avg_seconds) / 3600, 2) if avg_seconds is not None else None
        ),
        top_components=[ComponentCount(component=c, open_bugs=n) for c, n in component_rows],
        days=days,
    )
