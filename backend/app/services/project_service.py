"""Projects (FR-18) and team membership (FR-19). Every change is written to the audit log."""

from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import Bug, BugStatus, Project, ProjectMember, ProjectRole, User, UserRole
from app.schemas.project import MemberAdd, ProjectCreate, ProjectRead, ProjectUpdate
from app.services import audit_service
from app.services.access import ProjectAccess, ensure_writable, not_found, require_project_role


def _name_taken() -> AppError:
    return AppError(status.HTTP_409_CONFLICT, "name_taken", "A project with this name exists")


def to_read(project: Project, role: ProjectRole | None) -> ProjectRead:
    read = ProjectRead.model_validate(project)
    read.my_role = role
    return read


def create_project(db: Session, creator: User, data: ProjectCreate) -> Project:
    project = Project(name=data.name, description=data.description, created_by_id=creator.id)
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise _name_taken() from exc
    db.add(
        ProjectMember(project_id=project.id, user_id=creator.id, role=ProjectRole.PROJECT_MANAGER)
    )
    audit_service.record(db, creator, "project_created", project_id=project.id, new=project.name)
    audit_service.record(
        db,
        creator,
        "member_added",
        project_id=project.id,
        field="member",
        new=f"{audit_service.user_label(creator)} as {ProjectRole.PROJECT_MANAGER.value}",
    )
    db.commit()
    db.refresh(project)
    return project


def list_projects(
    db: Session, user: User, include_archived: bool
) -> list[tuple[Project, ProjectRole | None]]:
    role_col = ProjectMember.role
    query = select(Project, role_col).outerjoin(
        ProjectMember,
        (ProjectMember.project_id == Project.id) & (ProjectMember.user_id == user.id),
    )
    if user.role != UserRole.ADMINISTRATOR:
        query = query.where(ProjectMember.id.is_not(None))
    if not include_archived:
        query = query.where(Project.is_archived.is_(False))
    return [(p, r) for p, r in db.execute(query.order_by(Project.name)).all()]


def update_project(db: Session, access: ProjectAccess, data: ProjectUpdate) -> Project:
    require_project_role(access, ProjectRole.PROJECT_MANAGER)
    ensure_writable(access.project)
    project = access.project
    for name, value in data.model_dump(exclude_unset=True).items():
        if value is None or getattr(project, name) == value:
            continue
        audit_service.record(
            db,
            access.user,
            "project_updated",
            project_id=project.id,
            field=name,
            old=getattr(project, name),
            new=value,
        )
        setattr(project, name, value)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise _name_taken() from exc
    db.refresh(project)
    return project


def set_archived(db: Session, access: ProjectAccess, archived: bool) -> Project:
    project = access.project
    if archived:
        require_project_role(access, ProjectRole.PROJECT_MANAGER)
    elif not access.is_admin:
        raise AppError(
            status.HTTP_403_FORBIDDEN, "forbidden", "Only an Administrator can unarchive"
        )
    if project.is_archived == archived:
        state = "archived" if archived else "active"
        raise AppError(status.HTTP_409_CONFLICT, "no_change", f"Project is already {state}")
    project.is_archived = archived
    project.archived_at = datetime.now(UTC) if archived else None
    audit_service.record(
        db,
        access.user,
        "project_archived" if archived else "project_unarchived",
        project_id=project.id,
        field="is_archived",
        old=not archived,
        new=archived,
    )
    db.commit()
    db.refresh(project)
    return project


# --------------------------------------------------------------------------- membership
def list_members(db: Session, project_id: int) -> Sequence[ProjectMember]:
    return db.scalars(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id)
        .options(selectinload(ProjectMember.user))
        .join(User, User.id == ProjectMember.user_id)
        .order_by(User.full_name)
    ).all()


def _get_member(db: Session, project_id: int, user_id: int) -> ProjectMember:
    member = db.scalar(
        select(ProjectMember)
        .where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        .options(selectinload(ProjectMember.user))
    )
    if member is None:
        raise not_found("Member")
    return member


def _manager_count(db: Session, project_id: int) -> int:
    return (
        db.scalar(
            select(func.count()).where(
                ProjectMember.project_id == project_id,
                ProjectMember.role == ProjectRole.PROJECT_MANAGER,
            )
        )
        or 0
    )


def _guard_last_manager(db: Session, member: ProjectMember) -> None:
    if member.role == ProjectRole.PROJECT_MANAGER and _manager_count(db, member.project_id) <= 1:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "last_manager",
            "A project must keep at least one Project Manager",
        )


def add_member(db: Session, access: ProjectAccess, data: MemberAdd) -> ProjectMember:
    require_project_role(access, ProjectRole.PROJECT_MANAGER)
    ensure_writable(access.project)
    if data.user_id is not None:
        user = db.get(User, data.user_id)
    else:
        user = db.scalar(select(User).where(User.email == str(data.email).strip().lower()))
    if user is None or not user.is_active:
        raise not_found("User")
    member = ProjectMember(project_id=access.project.id, user_id=user.id, role=data.role)
    db.add(member)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise AppError(
            status.HTTP_409_CONFLICT, "already_member", "User is already a member"
        ) from exc
    audit_service.record(
        db,
        access.user,
        "member_added",
        project_id=access.project.id,
        field="member",
        new=f"{audit_service.user_label(user)} as {data.role.value}",
    )
    db.commit()
    return _get_member(db, access.project.id, user.id)


def change_member_role(
    db: Session, access: ProjectAccess, user_id: int, role: ProjectRole
) -> ProjectMember:
    require_project_role(access, ProjectRole.PROJECT_MANAGER)
    ensure_writable(access.project)
    member = _get_member(db, access.project.id, user_id)
    if member.role == role:
        return member
    if role != ProjectRole.PROJECT_MANAGER:
        _guard_last_manager(db, member)
    audit_service.record(
        db,
        access.user,
        "member_role_changed",
        project_id=access.project.id,
        field=f"role of {audit_service.user_label(member.user)}",
        old=member.role.value,
        new=role.value,
    )
    member.role = role
    db.commit()
    return _get_member(db, access.project.id, user_id)


def remove_member(db: Session, access: ProjectAccess, user_id: int) -> None:
    require_project_role(access, ProjectRole.PROJECT_MANAGER)
    ensure_writable(access.project)
    member = _get_member(db, access.project.id, user_id)
    _guard_last_manager(db, member)
    active_assigned = db.scalar(
        select(func.count()).where(
            Bug.project_id == access.project.id,
            Bug.assignee_id == user_id,
            Bug.status.in_((BugStatus.OPEN, BugStatus.IN_PROGRESS)),
        )
    )
    if active_assigned:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "member_has_active_bugs",
            f"Reassign this member's {active_assigned} active bug(s) first",
            {"active_bugs": active_assigned},
        )
    audit_service.record(
        db,
        access.user,
        "member_removed",
        project_id=access.project.id,
        field="member",
        old=f"{audit_service.user_label(member.user)} as {member.role.value}",
    )
    db.delete(member)
    db.commit()
