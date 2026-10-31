from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_role
from app.core.database import get_db
from app.models.project import Project, ProjectMember
from app.models.user import User, UserRole
from app.schemas.project import MemberAdd, MemberRead, ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


def _is_member(db: Session, project_id: int, user_id: int) -> bool:
    return (
        db.query(ProjectMember)
        .filter(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
        .first()
        is not None
    )


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.project_manager, UserRole.administrator)
    ),
):
    project = Project(name=payload.name, description=payload.description)
    db.add(project)
    db.commit()
    db.refresh(project)

    # The creator automatically joins the project they created.
    db.add(ProjectMember(project_id=project.id, user_id=current_user.id))
    db.commit()
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role == UserRole.administrator:
        return db.query(Project).all()
    return (
        db.query(Project)
        .join(ProjectMember, ProjectMember.project_id == Project.id)
        .filter(ProjectMember.user_id == current_user.id)
        .all()
    )


@router.get("/{project_id}", response_model=ProjectRead)
def get_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if current_user.role != UserRole.administrator and not _is_member(
        db, project_id, current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )
    return project


@router.post("/{project_id}/archive", response_model=ProjectRead)
def archive_project(
    project_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.project_manager, UserRole.administrator)
    ),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if current_user.role != UserRole.administrator and not _is_member(
        db, project_id, current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )
    project.is_archived = True
    db.commit()
    db.refresh(project)
    return project


@router.post(
    "/{project_id}/members",
    response_model=MemberRead,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    project_id: int,
    payload: MemberAdd,
    db: Session = Depends(get_db),
    current_user: User = Depends(
        require_role(UserRole.project_manager, UserRole.administrator)
    ),
):
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
        )
    if current_user.role != UserRole.administrator and not _is_member(
        db, project_id, current_user.id
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this project",
        )

    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if _is_member(db, project_id, payload.user_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="User is already a member"
        )

    member = ProjectMember(project_id=project_id, user_id=payload.user_id)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member
