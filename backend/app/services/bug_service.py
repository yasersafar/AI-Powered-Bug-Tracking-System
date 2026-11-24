"""Bug use cases: submission, edits, status lifecycle, assignment, severity override, search.

All writes record audit entries (FR-08) in the same transaction and commit at the end.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import status
from sqlalchemy import ColumnElement, Select, case, func, select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import (
    AiStatus,
    Bug,
    BugEmbedding,
    BugStatus,
    CloseReason,
    ProjectMember,
    ProjectRole,
    Severity,
    User,
)
from app.schemas.bug import BugCreate, BugRead, BugSort, BugUpdate, TransitionRequest
from app.services import audit_service, developer_activity, lifecycle, notification_service
from app.services.access import (
    ProjectAccess,
    accessible_project_ids,
    forbidden,
    require_project_role,
)

ACTIVE_STATUSES = (BugStatus.OPEN, BugStatus.IN_PROGRESS)
_LOAD_PEOPLE = (selectinload(Bug.reporter), selectinload(Bug.assignee))


@dataclass
class AiResult:
    """Output of the triage pipeline that is stored on the bug (FR-10..FR-12, NFR-10)."""

    ai_status: AiStatus = AiStatus.DEGRADED
    severity: Severity | None = None
    confidence: float | None = None
    duplicate_candidates: list[dict[str, Any]] = field(default_factory=list)
    recommended_developers: list[dict[str, Any]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    # Sentence embedding of the report (float32 bytes), saved in the same transaction as the
    # bug so a committed bug never needs to be re-encoded by another worker or request.
    embedding: bytes | None = None
    embedding_model: str | None = None


# --------------------------------------------------------------------------- read helpers
def load_bug(db: Session, bug_id: int) -> Bug:
    bug = db.scalar(select(Bug).where(Bug.id == bug_id).options(*_LOAD_PEOPLE))
    if bug is None:
        raise AppError(status.HTTP_404_NOT_FOUND, "not_found", "Bug not found")
    return bug


def to_read(bug: Bug, access: ProjectAccess) -> BugRead:
    """Serialize a bug together with what the caller is allowed to do with it."""
    read = BugRead.model_validate(bug)
    writable = not access.project.is_archived and bug.status != BugStatus.CLOSED
    read.allowed_transitions = lifecycle.allowed_targets(bug, access)
    read.can_override_severity = writable and access.has_role(
        ProjectRole.DEVELOPER, ProjectRole.PROJECT_MANAGER
    )
    read.can_assign = writable and access.is_manager and bug.status in ACTIVE_STATUSES
    read.can_edit = writable and (
        access.is_manager or bug.reporter_id == access.user.id or bug.assignee_id == access.user.id
    )
    return read


# --------------------------------------------------------------------------- create / edit
def create_bug(
    db: Session, access: ProjectAccess, reporter: User, data: BugCreate, ai: AiResult | None = None
) -> Bug:
    """FR-05. Without a predicted severity (pipeline down, step degraded or `ai` is None) the
    bug is still saved, with severity Unclassified (NFR-10)."""
    ai = ai or AiResult()
    severity = ai.severity or Severity.UNCLASSIFIED
    bug = Bug(
        project_id=access.project.id,
        reporter_id=reporter.id,
        title=data.title,
        description=data.description,
        steps_to_reproduce=data.steps_to_reproduce,
        environment=data.environment,
        components=data.components,
        status=BugStatus.OPEN,
        severity=severity,
        predicted_severity=ai.severity,
        severity_confidence=ai.confidence,
        duplicate_candidates=ai.duplicate_candidates,
        recommended_developers=ai.recommended_developers,
        ai_status=ai.ai_status,
        ai_details=ai.details,
    )
    db.add(bug)
    db.flush()
    if ai.embedding is not None and ai.embedding_model:
        db.add(
            BugEmbedding(
                bug_id=bug.id,
                model=ai.embedding_model,
                dimension=len(ai.embedding) // 4,
                vector=ai.embedding,
            )
        )
    audit_service.record(
        db, reporter, "created", bug_id=bug.id, field="status", new=bug.status.value
    )
    audit_service.record(
        db, None, "severity_predicted", bug_id=bug.id, field="severity", new=severity.value
    )
    if severity == Severity.CRITICAL:
        notification_service.notify_critical(db, bug, None)
    db.commit()
    return load_bug(db, bug.id)


def _ensure_open_for_changes(bug: Bug) -> None:
    if bug.status == BugStatus.CLOSED:
        raise AppError(status.HTTP_409_CONFLICT, "bug_closed", "Closed bugs cannot be changed")


def update_bug(db: Session, bug: Bug, access: ProjectAccess, data: BugUpdate) -> Bug:
    _ensure_open_for_changes(bug)
    actor = access.user
    if not (access.is_manager or actor.id in (bug.reporter_id, bug.assignee_id)):
        raise forbidden("Only the reporter, the assignee or a Project Manager can edit this bug")
    for name, new_value in data.model_dump(exclude_unset=True).items():
        if new_value is None:
            continue
        old_value = getattr(bug, name)
        if old_value == new_value:
            continue
        setattr(bug, name, new_value)
        audit_service.record(
            db, actor, "field_changed", bug_id=bug.id, field=name, old=old_value, new=new_value
        )
    db.commit()
    return load_bug(db, bug.id)


# --------------------------------------------------------------------------- lifecycle
def _set_status(
    db: Session, bug: Bug, actor: User, target: BugStatus, notify_skip: int | None = None
) -> None:
    old = bug.status
    bug.status = target
    now = datetime.now(UTC)
    if target == BugStatus.RESOLVED:
        bug.resolved_at = now
    elif target == BugStatus.IN_PROGRESS and old == BugStatus.RESOLVED:
        bug.resolved_at = None  # verification failed: reopened
    elif target == BugStatus.CLOSED:
        bug.closed_at = now
    audit_service.record(
        db, actor, "status_changed", bug_id=bug.id, field="status", old=old.value, new=target.value
    )
    if target == BugStatus.RESOLVED:
        developer_activity.on_resolved(db, bug, now)
    elif target == BugStatus.IN_PROGRESS and old == BugStatus.RESOLVED:
        developer_activity.on_reopened(db, bug)
    elif target == BugStatus.CLOSED:
        developer_activity.on_closed(db, bug)
    notification_service.notify_status_changed(
        db, bug, actor, old, target, skip_user_id=notify_skip
    )


def transition(db: Session, bug: Bug, access: ProjectAccess, request: TransitionRequest) -> Bug:
    target = request.to_status
    lifecycle.check_transition(bug, access, target)
    actor = access.user

    if bug.status == BugStatus.OPEN and target == BugStatus.IN_PROGRESS and bug.assignee_id is None:
        raise AppError(
            status.HTTP_409_CONFLICT, "bug_unassigned", "Assign a developer before starting work"
        )

    if target == BugStatus.CLOSED:
        if bug.status == BugStatus.OPEN:
            if request.close_reason is None:
                raise AppError(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "validation_error",
                    "close_reason ('invalid' or 'duplicate') is required to close an Open bug",
                )
            reason = CloseReason(request.close_reason)
            if reason == CloseReason.DUPLICATE:
                _set_duplicate_of(db, bug, actor, request.duplicate_of_id)
        else:
            if request.close_reason is not None:
                raise AppError(
                    status.HTTP_422_UNPROCESSABLE_CONTENT,
                    "validation_error",
                    "close_reason is only used when closing an Open bug",
                )
            reason = CloseReason.FIXED
        bug.close_reason = reason
        audit_service.record(
            db, actor, "field_changed", bug_id=bug.id, field="close_reason", new=reason.value
        )
    elif request.close_reason is not None:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error",
            "close_reason is only allowed when closing a bug",
        )

    _set_status(db, bug, actor, target)
    db.commit()
    return load_bug(db, bug.id)


def _set_duplicate_of(db: Session, bug: Bug, actor: User, original_id: int | None) -> None:
    original = db.get(Bug, original_id) if original_id is not None else None
    if original is None or original.project_id != bug.project_id or original.id == bug.id:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_duplicate",
            "duplicate_of_id must be another bug in the same project",
        )
    bug.duplicate_of_id = original.id
    audit_service.record(
        db, actor, "field_changed", bug_id=bug.id, field="duplicate_of", new=f"#{original.id}"
    )


def assign(db: Session, bug: Bug, access: ProjectAccess, assignee_id: int) -> Bug:
    """Project Manager assigns (or reassigns) a developer. Open bugs move to InProgress."""
    require_project_role(access, ProjectRole.PROJECT_MANAGER)
    if bug.status not in ACTIVE_STATUSES:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "invalid_state",
            f"Bugs in status {bug.status.value} cannot be (re)assigned",
        )
    member = db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == bug.project_id, ProjectMember.user_id == assignee_id)
        .options(selectinload(ProjectMember.user))
    )
    if (
        member is None
        or not member.user.is_active
        or member.role not in (ProjectRole.DEVELOPER, ProjectRole.PROJECT_MANAGER)
    ):
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_assignee",
            "The assignee must be an active Developer or Project Manager of this project",
        )
    if bug.assignee_id == assignee_id:
        return load_bug(db, bug.id)

    previous = db.get(User, bug.assignee_id) if bug.assignee_id else None
    bug.assignee_id = assignee_id
    audit_service.record(
        db,
        access.user,
        "reassigned" if previous else "assigned",
        bug_id=bug.id,
        field="assignee",
        old=audit_service.user_label(previous),
        new=audit_service.user_label(member.user),
    )
    developer_activity.on_assigned(db, bug, assignee_id, access.user.id)
    if bug.status == BugStatus.OPEN:
        # The assignee gets the "assigned" notification below instead of a status change.
        _set_status(db, bug, access.user, BugStatus.IN_PROGRESS, notify_skip=assignee_id)
    notification_service.notify_assigned(db, bug, access.user, member.user)
    db.commit()
    return load_bug(db, bug.id)


def override_severity(db: Session, bug: Bug, access: ProjectAccess, severity: Severity) -> Bug:
    """FR-11: Developers and Project Managers may override the predicted severity (audited)."""
    require_project_role(access, ProjectRole.DEVELOPER, ProjectRole.PROJECT_MANAGER)
    _ensure_open_for_changes(bug)
    if bug.severity == severity and bug.severity_overridden:
        return load_bug(db, bug.id)
    old = bug.severity
    bug.severity = severity
    bug.severity_overridden = True
    audit_service.record(
        db,
        access.user,
        "severity_overridden",
        bug_id=bug.id,
        field="severity",
        old=old.value,
        new=severity.value,
    )
    if severity == Severity.CRITICAL and old != Severity.CRITICAL:
        notification_service.notify_critical(db, bug, access.user)
    db.commit()
    return load_bug(db, bug.id)


# --------------------------------------------------------------------------- search (FR-07)
@dataclass
class BugFilters:
    project_id: int | None = None
    status: list[BugStatus] | None = None
    severity: list[Severity] | None = None
    assignee_id: int | None = None
    reporter_id: int | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    q: str | None = None
    sort: BugSort = "created_desc"


_SEVERITY_RANK = case(
    {
        Severity.CRITICAL: 4,
        Severity.HIGH: 3,
        Severity.MEDIUM: 2,
        Severity.LOW: 1,
    },
    value=Bug.severity,
    else_=0,
)


def _filtered(db: Session, user: User, filters: BugFilters) -> tuple[Select[Bug], Any]:
    conditions: list[ColumnElement[bool]] = []
    visible = accessible_project_ids(db, user)
    if filters.project_id is not None:
        if visible is not None and filters.project_id not in visible:
            raise forbidden("You are not a member of this project")
        conditions.append(Bug.project_id == filters.project_id)
    elif visible is not None:
        conditions.append(Bug.project_id.in_(visible))
    if filters.status:
        conditions.append(Bug.status.in_(filters.status))
    if filters.severity:
        conditions.append(Bug.severity.in_(filters.severity))
    if filters.assignee_id is not None:
        conditions.append(Bug.assignee_id == filters.assignee_id)
    if filters.reporter_id is not None:
        conditions.append(Bug.reporter_id == filters.reporter_id)
    if filters.created_from is not None:
        conditions.append(Bug.created_at >= filters.created_from)
    if filters.created_to is not None:
        conditions.append(Bug.created_at <= filters.created_to)

    ts_query = None
    if filters.q:
        # websearch_to_tsquery accepts free text safely ("quoted phrases", -exclusions, OR).
        ts_query = func.websearch_to_tsquery("english", filters.q)
        conditions.append(Bug.search_vector.op("@@")(ts_query))
    return select(Bug).where(*conditions), ts_query


def search(
    db: Session, user: User, filters: BugFilters, page: int, page_size: int
) -> tuple[list[Bug], int]:
    query, ts_query = _filtered(db, user, filters)
    total = db.scalar(select(func.count()).select_from(query.order_by(None).subquery())) or 0

    if filters.sort == "relevance" and ts_query is not None:
        order: list[Any] = [func.ts_rank(Bug.search_vector, ts_query).desc(), Bug.id.desc()]
    elif filters.sort == "created_asc":
        order = [Bug.created_at.asc(), Bug.id.asc()]
    elif filters.sort == "updated_desc":
        order = [Bug.updated_at.desc(), Bug.id.desc()]
    elif filters.sort == "severity_desc":
        order = [_SEVERITY_RANK.desc(), Bug.created_at.desc(), Bug.id.desc()]
    else:
        order = [Bug.created_at.desc(), Bug.id.desc()]

    items = db.scalars(
        query.options(*_LOAD_PEOPLE)
        .order_by(*order)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return list(items), total
