"""Triage endpoints (FR-10, FR-11, FR-12, FR-22). They never fail because of the models:
a failing, slow or switched-off step is returned as `degraded` with a notice (NFR-10)."""

from collections.abc import Sequence

from fastapi import APIRouter

from app.core.deps import CurrentUser, DbSession, Triage
from app.core.errors import ErrorResponse
from app.models import Bug
from app.schemas.ai import (
    AiStatusResponse,
    AssignRequest,
    DuplicateCheckRequest,
    SeverityRequest,
    TriageRequest,
    TriageResponse,
)
from app.services import settings_service, triage_service
from app.services.access import not_found, project_access
from app.services.triage_service import AiOutcome
from ml.service.context import ALL_STEPS_ORDER, ASSIGNMENT, DUPLICATES, SEVERITY

router = APIRouter(prefix="/ai", tags=["ai"])

_ERRORS: dict[int | str, dict[str, object]] = {
    403: {"model": ErrorResponse, "description": "Not a member of the project"},
    404: {"model": ErrorResponse, "description": "Project not found"},
}


def _response(outcome: AiOutcome) -> TriageResponse:
    return TriageResponse.model_validate(
        {
            "ai_status": outcome.ai_status,
            "notice": outcome.notice,
            "duplicates": outcome.duplicates,
            "is_likely_duplicate": outcome.is_likely_duplicate,
            "severity": {
                "severity": outcome.severity,
                "confidence": outcome.confidence,
                "probabilities": outcome.probabilities,
            },
            "recommendations": outcome.recommendations,
            "steps": outcome.steps,
            "total_ms": outcome.total_ms,
        }
    )


@router.post(
    "/triage",
    response_model=TriageResponse,
    summary="Run the full triage pipeline on a draft report",
    description=(
        "Duplicates -> severity -> developer recommendation over one shared context: a likely "
        "duplicate boosts the developers who fixed the original, and a Critical prediction "
        "filters out unavailable developers and those at their maximum workload."
    ),
    responses=_ERRORS,
)
def triage(data: TriageRequest, user: CurrentUser, db: DbSession, engine: Triage) -> TriageResponse:
    project_access(db, user, data.project_id)
    return _response(
        engine.run(
            db,
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            components=data.components,
            steps=ALL_STEPS_ORDER,
        )
    )


@router.post(
    "/duplicates",
    response_model=TriageResponse,
    summary="Find possible duplicates while the user types",
    description="Top-k earlier reports of the same project with a similarity score (FR-10).",
    responses=_ERRORS,
)
def duplicates(
    data: DuplicateCheckRequest, user: CurrentUser, db: DbSession, engine: Triage
) -> TriageResponse:
    project_access(db, user, data.project_id)
    exclude: Sequence[int] = [data.exclude_bug_id] if data.exclude_bug_id is not None else []
    return _response(
        engine.run(
            db,
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            steps=[DUPLICATES],
            exclude_bug_ids=exclude,
        )
    )


@router.post(
    "/severity",
    response_model=TriageResponse,
    summary="Predict the severity of a draft report",
    description="Soft-voting ensemble; returns the label, its confidence and all class "
    "probabilities (FR-11).",
)
def severity(
    data: SeverityRequest, user: CurrentUser, db: DbSession, engine: Triage
) -> TriageResponse:
    return _response(
        engine.run(
            db, project_id=0, title=data.title, description=data.description, steps=[SEVERITY]
        )
    )


@router.post(
    "/assign",
    response_model=TriageResponse,
    summary="Recommend developers for a report",
    description=(
        "Top-3 developers of the project with score and reason (FR-12) using the hybrid "
        "cold-start blend (FR-22). Optional `severity` and `duplicate_of_ids` provide the "
        "shared state that the full pipeline would otherwise compute."
    ),
    responses=_ERRORS,
)
def assign(data: AssignRequest, user: CurrentUser, db: DbSession, engine: Triage) -> TriageResponse:
    project_access(db, user, data.project_id)
    originals = [
        b
        for b in data.duplicate_of_ids
        if (bug := db.get(Bug, b)) is not None and bug.project_id == data.project_id
    ]
    if len(originals) != len(data.duplicate_of_ids):
        raise not_found("Bug")
    return _response(
        engine.run(
            db,
            project_id=data.project_id,
            title=data.title,
            description=data.description,
            components=data.components,
            steps=[ASSIGNMENT],
            severity_hint=data.severity,
            duplicate_hint=originals,
        )
    )


@router.get(
    "/status",
    response_model=AiStatusResponse,
    summary="State of the triage models",
    description="Lets the extension explain why AI results are missing.",
)
def ai_status(user: CurrentUser, db: DbSession, engine: Triage) -> AiStatusResponse:
    return AiStatusResponse.model_validate(
        {
            **engine.status(),
            "enabled": bool(settings_service.get_value(db, "ai_enabled")),
            "served_models": triage_service.model_states(db),
        }
    )
