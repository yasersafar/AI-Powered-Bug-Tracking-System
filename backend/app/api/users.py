"""Own profile (FR-04) and user administration (FR-03)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.deps import AppSettings, CurrentUser, DbSession, require_global_role
from app.core.security import create_access_token
from app.models import User, UserRole
from app.schemas.audit import AuditEntryRead
from app.schemas.common import Page, UserSummary
from app.schemas.user import (
    AdminUserUpdate,
    ChangePasswordRequest,
    TokenResponse,
    UpdateMeRequest,
    UserMe,
    UserRead,
)
from app.services import audit_service, user_service
from app.services.access import not_found

router = APIRouter(prefix="/users", tags=["users"])

AdminUser = Annotated[User, Depends(require_global_role(UserRole.ADMINISTRATOR))]
ManagerOrAdmin = Annotated[
    User, Depends(require_global_role(UserRole.PROJECT_MANAGER, UserRole.ADMINISTRATOR))
]


@router.get("/me", response_model=UserMe, summary="Current user's profile")
def read_me(user: CurrentUser) -> UserMe:
    return UserMe.model_validate(user)


@router.patch("/me", response_model=UserMe, summary="Edit own name and notification preferences")
def update_me(data: UpdateMeRequest, user: CurrentUser, db: DbSession) -> UserMe:
    return UserMe.model_validate(user_service.update_me(db, user, data))


@router.post(
    "/me/password",
    response_model=TokenResponse,
    summary="Change own password",
    description="All previously issued tokens stop working; a fresh token is returned.",
)
def change_password(
    data: ChangePasswordRequest, user: CurrentUser, db: DbSession, settings: AppSettings
) -> TokenResponse:
    updated = user_service.change_password(
        db, user, data.current_password, data.new_password, settings
    )
    return TokenResponse(
        access_token=create_access_token(updated.id, settings, updated.token_version),
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserMe.model_validate(updated),
    )


@router.get(
    "",
    response_model=Page[UserSummary],
    summary="Search active users (Project Managers and Administrators)",
    description="Used to find people to add to a project. Matches e-mail or name.",
)
def search_users(
    _: ManagerOrAdmin,
    db: DbSession,
    q: Annotated[str | None, Query(min_length=2, max_length=100)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[UserSummary]:
    users, total = user_service.search_users(db, q, page, page_size, active_only=True)
    return Page(
        items=[UserSummary.model_validate(u) for u in users],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.patch(
    "/{user_id}",
    response_model=UserRead,
    summary="Change a user's global role or active flag (Administrator)",
)
def admin_update_user(
    user_id: int, data: AdminUserUpdate, admin: AdminUser, db: DbSession
) -> UserRead:
    target = db.get(User, user_id)
    if target is None:
        raise not_found("User")
    return UserRead.model_validate(user_service.admin_update(db, admin, target, data))


@router.get(
    "/{user_id}/audit",
    response_model=list[AuditEntryRead],
    summary="Account audit history (Administrator)",
)
def user_audit(user_id: int, _: AdminUser, db: DbSession) -> list[AuditEntryRead]:
    if db.get(User, user_id) is None:
        raise not_found("User")
    return [AuditEntryRead.model_validate(e) for e in audit_service.user_history(db, user_id)]
