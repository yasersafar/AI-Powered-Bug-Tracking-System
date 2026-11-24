"""Bugs: submission (FR-05), lifecycle (FR-06), search (FR-07), audit (FR-08), override (FR-11)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.dispatch import Dispatcher
from app.core.deps import CurrentUser, DbSession, Triage
from app.core.errors import ErrorResponse
from app.models import BugStatus, Severity
from app.schemas.audit import AuditEntryRead
from app.schemas.bug import (
    AssignRequest,
    BugCreate,
    BugListItem,
    BugRead,
    BugSort,
    BugUpdate,
    SeverityOverrideRequest,
    TransitionRequest,
)
from app.schemas.common import Page
from app.services import audit_service, bug_service
from app.services.access import bug_access, project_access
from app.services.triage_service import EMBEDDING_MODEL

router = APIRouter(prefix="/bugs", tags=["bugs"])

_ERRORS: dict[int | str, dict[str, object]] = {
    403: {"model": ErrorResponse, "description": "Not allowed for your role or project"},
    404: {"model": ErrorResponse, "description": "Bug not found"},
    409: {"model": ErrorResponse, "description": "Invalid state change or archived project"},
}


@router.post(
    "",
    response_model=BugRead,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a bug report",
    responses=_ERRORS,
)
def create_bug(
    data: BugCreate, user: CurrentUser, db: DbSession, dispatcher: Dispatcher, engine: Triage
) -> BugRead:
    access = project_access(db, user, data.project_id, write=True)
    # FR-10..FR-12 on submit. `run` never raises: a degraded triage still saves the bug as
    # Unclassified (NFR-10) and `ai_details.notice` explains why.
    outcome = engine.run(
        db,
        project_id=data.project_id,
        title=data.title,
        description=data.description,
        components=data.components,
    )
    ai = bug_service.AiResult(
        ai_status=outcome.ai_status,
        severity=outcome.severity,
        confidence=outcome.confidence,
        duplicate_candidates=outcome.duplicates,
        recommended_developers=outcome.recommendations,
        details=outcome.details,
        embedding=None if outcome.vector is None else outcome.vector.tobytes(),
        embedding_model=EMBEDDING_MODEL,
    )
    bug = bug_service.create_bug(db, access, user, data, ai)
    dispatcher.flush()
    engine.index_bug(db, bug, outcome.vector)
    return bug_service.to_read(bug, access)


@router.get(
    "",
    response_model=Page[BugListItem],
    summary="Search and filter bugs",
    description=(
        "All filters are optional and combine with AND. `q` is a full-text search over title "
        'and description (PostgreSQL `websearch_to_tsquery`: supports "phrases", -exclude, OR). '
        "Only bugs from the caller's projects are returned."
    ),
)
def list_bugs(
    user: CurrentUser,
    db: DbSession,
    project_id: int | None = None,
    status_: Annotated[list[BugStatus] | None, Query(alias="status")] = None,
    severity: Annotated[list[Severity] | None, Query()] = None,
    assignee_id: int | None = None,
    reporter_id: int | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    q: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    sort: BugSort = "created_desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[BugListItem]:
    filters = bug_service.BugFilters(
        project_id=project_id,
        status=status_,
        severity=severity,
        assignee_id=assignee_id,
        reporter_id=reporter_id,
        created_from=created_from,
        created_to=created_to,
        q=q.strip() if q else None,
        sort=sort,
    )
    bugs, total = bug_service.search(db, user, filters, page, page_size)
    return Page(
        items=[BugListItem.model_validate(b) for b in bugs],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{bug_id}", response_model=BugRead, summary="Bug details", responses=_ERRORS)
def get_bug(bug_id: int, user: CurrentUser, db: DbSession) -> BugRead:
    bug, access = bug_access(db, user, bug_id)
    return bug_service.to_read(bug_service.load_bug(db, bug.id), access)


@router.patch("/{bug_id}", response_model=BugRead, summary="Edit bug fields", responses=_ERRORS)
def update_bug(
    bug_id: int, data: BugUpdate, user: CurrentUser, db: DbSession, engine: Triage
) -> BugRead:
    bug, access = bug_access(db, user, bug_id, write=True)
    before = (bug.title, bug.description)
    updated = bug_service.update_bug(db, bug, access, data)
    if (updated.title, updated.description) != before:
        engine.forget_text(db, updated)  # re-embedded on the next duplicate search
    return bug_service.to_read(updated, access)


@router.post(
    "/{bug_id}/transitions",
    response_model=BugRead,
    summary="Change bug status",
    description="Invalid transitions return 409; a valid transition by the wrong role returns 403.",
    responses=_ERRORS,
)
def transition_bug(
    bug_id: int, data: TransitionRequest, user: CurrentUser, db: DbSession, dispatcher: Dispatcher
) -> BugRead:
    bug, access = bug_access(db, user, bug_id, write=True)
    updated = bug_service.transition(db, bug, access, data)
    dispatcher.flush()
    return bug_service.to_read(updated, access)


@router.post(
    "/{bug_id}/assign",
    response_model=BugRead,
    summary="Assign or reassign a developer (Project Manager)",
    responses=_ERRORS,
)
def assign_bug(
    bug_id: int, data: AssignRequest, user: CurrentUser, db: DbSession, dispatcher: Dispatcher
) -> BugRead:
    bug, access = bug_access(db, user, bug_id, write=True)
    updated = bug_service.assign(db, bug, access, data.assignee_id)
    dispatcher.flush()
    return bug_service.to_read(updated, access)


@router.post(
    "/{bug_id}/severity",
    response_model=BugRead,
    summary="Override the predicted severity (Developer / Project Manager)",
    responses=_ERRORS,
)
def override_severity(
    bug_id: int,
    data: SeverityOverrideRequest,
    user: CurrentUser,
    db: DbSession,
    dispatcher: Dispatcher,
) -> BugRead:
    bug, access = bug_access(db, user, bug_id, write=True)
    updated = bug_service.override_severity(db, bug, access, Severity(data.severity))
    dispatcher.flush()
    return bug_service.to_read(updated, access)


@router.get(
    "/{bug_id}/audit",
    response_model=list[AuditEntryRead],
    summary="Full change history of a bug",
    responses=_ERRORS,
)
def bug_audit(bug_id: int, user: CurrentUser, db: DbSession) -> list[AuditEntryRead]:
    bug, _ = bug_access(db, user, bug_id)
    return [AuditEntryRead.model_validate(e) for e in audit_service.bug_history(db, bug.id)]
