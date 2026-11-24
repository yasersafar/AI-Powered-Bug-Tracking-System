"""Projects (FR-18) and team membership (FR-19)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.deps import CurrentUser, DbSession, require_global_role
from app.models import ProjectRole, User, UserRole
from app.schemas.audit import AuditEntryRead
from app.schemas.dashboard import ProjectDashboard
from app.schemas.project import (
    MemberAdd,
    MemberRead,
    MemberUpdate,
    ProjectCreate,
    ProjectRead,
    ProjectUpdate,
)
from app.services import audit_service, project_service, stats_service
from app.services.access import project_access, require_project_role

router = APIRouter(prefix="/projects", tags=["projects"])

ProjectCreator = Annotated[
    User, Depends(require_global_role(UserRole.PROJECT_MANAGER, UserRole.ADMINISTRATOR))
]


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project (Project Manager / Administrator); creator becomes its PM",
)
def create_project(data: ProjectCreate, user: ProjectCreator, db: DbSession) -> ProjectRead:
    project = project_service.create_project(db, user, data)
    return project_service.to_read(project, ProjectRole.PROJECT_MANAGER)


@router.get("", response_model=list[ProjectRead], summary="Projects visible to the caller")
def list_projects(
    user: CurrentUser,
    db: DbSession,
    include_archived: Annotated[bool, Query()] = True,
) -> list[ProjectRead]:
    return [
        project_service.to_read(project, role)
        for project, role in project_service.list_projects(db, user, include_archived)
    ]


@router.get("/{project_id}", response_model=ProjectRead, summary="Project details")
def get_project(project_id: int, user: CurrentUser, db: DbSession) -> ProjectRead:
    access = project_access(db, user, project_id)
    return project_service.to_read(access.project, access.role)


@router.patch("/{project_id}", response_model=ProjectRead, summary="Rename / edit a project")
def update_project(
    project_id: int, data: ProjectUpdate, user: CurrentUser, db: DbSession
) -> ProjectRead:
    access = project_access(db, user, project_id)
    return project_service.to_read(project_service.update_project(db, access, data), access.role)


@router.post(
    "/{project_id}/archive",
    response_model=ProjectRead,
    summary="Archive a project (read-only afterwards, no new bugs)",
)
def archive_project(project_id: int, user: CurrentUser, db: DbSession) -> ProjectRead:
    access = project_access(db, user, project_id)
    return project_service.to_read(project_service.set_archived(db, access, True), access.role)


@router.post(
    "/{project_id}/unarchive",
    response_model=ProjectRead,
    summary="Make an archived project writable again (Administrator)",
)
def unarchive_project(project_id: int, user: CurrentUser, db: DbSession) -> ProjectRead:
    access = project_access(db, user, project_id)
    return project_service.to_read(project_service.set_archived(db, access, False), access.role)


@router.get("/{project_id}/members", response_model=list[MemberRead], summary="Project members")
def list_members(project_id: int, user: CurrentUser, db: DbSession) -> list[MemberRead]:
    project_access(db, user, project_id)
    return [MemberRead.model_validate(m) for m in project_service.list_members(db, project_id)]


@router.post(
    "/{project_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a member with a project role (Project Manager)",
)
def add_member(project_id: int, data: MemberAdd, user: CurrentUser, db: DbSession) -> MemberRead:
    access = project_access(db, user, project_id)
    return MemberRead.model_validate(project_service.add_member(db, access, data))


@router.patch(
    "/{project_id}/members/{user_id}",
    response_model=MemberRead,
    summary="Change a member's project role (Project Manager)",
)
def change_member_role(
    project_id: int, user_id: int, data: MemberUpdate, user: CurrentUser, db: DbSession
) -> MemberRead:
    access = project_access(db, user, project_id)
    member = project_service.change_member_role(db, access, user_id, data.role)
    return MemberRead.model_validate(member)


@router.delete(
    "/{project_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a member (Project Manager)",
)
def remove_member(project_id: int, user_id: int, user: CurrentUser, db: DbSession) -> None:
    access = project_access(db, user, project_id)
    project_service.remove_member(db, access, user_id)


@router.get(
    "/{project_id}/audit",
    response_model=list[AuditEntryRead],
    summary="Project and membership audit history (Project Manager)",
)
def project_audit(project_id: int, user: CurrentUser, db: DbSession) -> list[AuditEntryRead]:
    access = project_access(db, user, project_id)
    require_project_role(access, ProjectRole.PROJECT_MANAGER)
    return [AuditEntryRead.model_validate(e) for e in audit_service.project_history(db, project_id)]


@router.get(
    "/{project_id}/dashboard",
    response_model=ProjectDashboard,
    summary="Counts by status/severity, bugs over time, average resolution time (FR-15)",
)
def dashboard(
    project_id: int,
    user: CurrentUser,
    db: DbSession,
    days: Annotated[int, Query(ge=7, le=365)] = 30,
) -> ProjectDashboard:
    project_access(db, user, project_id)
    return stats_service.project_dashboard(db, project_id, days)
