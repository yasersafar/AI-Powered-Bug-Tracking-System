"""Project-scoped authorization (FR-03, NFR-06).

Every request that touches project data goes through `project_access`, which returns the
caller's role in that project. Administrators may act on every project. Other users only see
projects they are members of; anything else is a 403 and its content is never returned.
"""

from dataclasses import dataclass

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import Bug, Project, ProjectMember, ProjectRole, User, UserRole


@dataclass(frozen=True)
class ProjectAccess:
    project: Project
    user: User
    role: ProjectRole | None  # None = Administrator who is not a member

    @property
    def is_admin(self) -> bool:
        return self.user.role == UserRole.ADMINISTRATOR

    @property
    def is_manager(self) -> bool:
        return self.is_admin or self.role == ProjectRole.PROJECT_MANAGER

    def has_role(self, *roles: ProjectRole) -> bool:
        return self.is_admin or self.role in roles


def forbidden(message: str = "You do not have access to this resource") -> AppError:
    return AppError(status.HTTP_403_FORBIDDEN, "forbidden", message)


def not_found(what: str) -> AppError:
    return AppError(status.HTTP_404_NOT_FOUND, "not_found", f"{what} not found")


def membership_role(db: Session, project_id: int, user_id: int) -> ProjectRole | None:
    return db.scalar(
        select(ProjectMember.role).where(
            ProjectMember.project_id == project_id, ProjectMember.user_id == user_id
        )
    )


def project_access(
    db: Session, user: User, project_id: int, *, write: bool = False
) -> ProjectAccess:
    project = db.get(Project, project_id)
    if project is None:
        raise not_found("Project")
    role = membership_role(db, project_id, user.id)
    access = ProjectAccess(project=project, user=user, role=role)
    if role is None and not access.is_admin:
        raise forbidden("You are not a member of this project")
    if write:
        ensure_writable(project)
    return access


def ensure_writable(project: Project) -> None:
    """FR-18: archived projects are read-only."""
    if project.is_archived:
        raise AppError(
            status.HTTP_409_CONFLICT, "project_archived", "This project is archived and read-only"
        )


def require_project_role(access: ProjectAccess, *roles: ProjectRole) -> None:
    if not access.has_role(*roles):
        raise forbidden("Your project role does not allow this action")


def bug_access(
    db: Session, user: User, bug_id: int, *, write: bool = False
) -> tuple[Bug, ProjectAccess]:
    bug = db.get(Bug, bug_id)
    if bug is None:
        raise not_found("Bug")
    return bug, project_access(db, user, bug.project_id, write=write)


def accessible_project_ids(db: Session, user: User) -> list[int] | None:
    """Project ids the user may read; None means all (Administrator)."""
    if user.role == UserRole.ADMINISTRATOR:
        return None
    return list(
        db.scalars(select(ProjectMember.project_id).where(ProjectMember.user_id == user.id))
    )
