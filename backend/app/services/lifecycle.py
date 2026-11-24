"""Bug status state machine (FR-06).

    Open       -> InProgress   Project Manager (on assign) or the assigned Developer
    InProgress -> Resolved     the assigned Developer
    Resolved   -> Verified     the bug's reporter or a Reporter/QA member
    Resolved   -> InProgress   the bug's reporter or a Reporter/QA member (verification failed)
    Verified   -> Closed       Project Manager
    Open       -> Closed       Project Manager (invalid or duplicate)

Any other pair is a 409 Conflict. A listed pair attempted by the wrong role is a 403.
Administrators may perform every listed transition.
"""

from collections.abc import Callable

from fastapi import status

from app.core.errors import AppError
from app.models import Bug, BugStatus, ProjectRole
from app.services.access import ProjectAccess, forbidden

Rule = Callable[[Bug, ProjectAccess], bool]


def _manager(_: Bug, access: ProjectAccess) -> bool:
    return access.is_manager


def _assignee(bug: Bug, access: ProjectAccess) -> bool:
    return access.is_admin or (bug.assignee_id is not None and bug.assignee_id == access.user.id)


def _manager_or_assignee(bug: Bug, access: ProjectAccess) -> bool:
    return _manager(bug, access) or _assignee(bug, access)


def _verifier(bug: Bug, access: ProjectAccess) -> bool:
    return (
        access.is_admin or bug.reporter_id == access.user.id or access.role == ProjectRole.REPORTER
    )


TRANSITIONS: dict[tuple[BugStatus, BugStatus], Rule] = {
    (BugStatus.OPEN, BugStatus.IN_PROGRESS): _manager_or_assignee,
    (BugStatus.IN_PROGRESS, BugStatus.RESOLVED): _assignee,
    (BugStatus.RESOLVED, BugStatus.VERIFIED): _verifier,
    (BugStatus.RESOLVED, BugStatus.IN_PROGRESS): _verifier,
    (BugStatus.VERIFIED, BugStatus.CLOSED): _manager,
    (BugStatus.OPEN, BugStatus.CLOSED): _manager,
}


def valid_targets(current: BugStatus) -> list[BugStatus]:
    return [to for (frm, to) in TRANSITIONS if frm == current]


def allowed_targets(bug: Bug, access: ProjectAccess) -> list[BugStatus]:
    """Targets this caller may choose right now (used to render status buttons)."""
    if access.project.is_archived:
        return []
    return [
        to for (frm, to), rule in TRANSITIONS.items() if frm == bug.status and rule(bug, access)
    ]


def check_transition(bug: Bug, access: ProjectAccess, target: BugStatus) -> None:
    rule = TRANSITIONS.get((bug.status, target))
    if rule is None:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "invalid_transition",
            f"Cannot change status from {bug.status.value} to {target.value}",
            {
                "from": bug.status.value,
                "to": target.value,
                "valid_targets": [s.value for s in valid_targets(bug.status)],
            },
        )
    if not rule(bug, access):
        raise forbidden(f"Your role cannot move a bug from {bug.status.value} to {target.value}")
