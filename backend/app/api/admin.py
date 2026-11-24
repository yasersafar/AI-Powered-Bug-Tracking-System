"""Administrator area: developer profiles (FR-20), developer tracking (FR-21), settings (NFR-14)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.deps import DbSession, require_global_role
from app.models import User, UserRole
from app.schemas.admin import (
    DeveloperStats,
    ProfileCreate,
    ProfileRead,
    ProfileUpdate,
    SettingRead,
    SettingsUpdate,
)
from app.schemas.audit import AuditEntryRead
from app.schemas.common import UserSummary
from app.services import audit_service, profile_service, settings_service, stats_service
from app.services.access import not_found

router = APIRouter(prefix="/admin", tags=["admin"])
AdminUser = Annotated[User, Depends(require_global_role(UserRole.ADMINISTRATOR))]


# --------------------------------------------------------------------------- profiles
@router.get("/profiles", response_model=list[ProfileRead], summary="List developer profiles")
def list_profiles(
    _: AdminUser,
    db: DbSession,
    active: bool | None = None,
    cold_start: bool | None = None,
) -> list[ProfileRead]:
    return [
        ProfileRead.model_validate(p) for p in profile_service.list_profiles(db, active, cold_start)
    ]


@router.post(
    "/profiles",
    response_model=ProfileRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a developer profile",
)
def create_profile(data: ProfileCreate, admin: AdminUser, db: DbSession) -> ProfileRead:
    return ProfileRead.model_validate(profile_service.create_profile(db, admin, data))


@router.get("/profiles/{profile_id}", response_model=ProfileRead, summary="Developer profile")
def get_profile(profile_id: int, _: AdminUser, db: DbSession) -> ProfileRead:
    return ProfileRead.model_validate(profile_service.get_profile(db, profile_id))


@router.patch(
    "/profiles/{profile_id}",
    response_model=ProfileRead,
    summary="Edit a profile (set `active: false` to deactivate)",
)
def update_profile(
    profile_id: int, data: ProfileUpdate, admin: AdminUser, db: DbSession
) -> ProfileRead:
    profile = profile_service.get_profile(db, profile_id)
    return ProfileRead.model_validate(profile_service.update_profile(db, admin, profile, data))


@router.get(
    "/profiles/{profile_id}/audit",
    response_model=list[AuditEntryRead],
    summary="Profile change history",
)
def profile_audit(profile_id: int, _: AdminUser, db: DbSession) -> list[AuditEntryRead]:
    profile_service.get_profile(db, profile_id)
    return [AuditEntryRead.model_validate(e) for e in audit_service.profile_history(db, profile_id)]


# --------------------------------------------------------------------------- developer stats
@router.get(
    "/developers/stats",
    response_model=list[DeveloperStats],
    summary="Tracking figures for every developer",
)
def all_stats(_: AdminUser, db: DbSession) -> list[DeveloperStats]:
    return stats_service.all_developer_stats(db)


@router.get(
    "/developers/{user_id}/stats",
    response_model=DeveloperStats,
    summary="Resolved bugs, average resolution time, reassignments, workload (FR-21)",
)
def developer_stats(user_id: int, _: AdminUser, db: DbSession) -> DeveloperStats:
    user = db.get(User, user_id)
    if user is None:
        raise not_found("User")
    return stats_service.developer_stats(db, user)


# --------------------------------------------------------------------------- settings
def _settings_read(db: DbSession) -> list[SettingRead]:
    return [
        SettingRead(
            key=item.spec.key,
            value=item.value,
            default=item.spec.default,
            minimum=item.spec.minimum,
            maximum=item.spec.maximum,
            type=item.spec.kind.__name__,
            unit=item.spec.unit,
            description=item.spec.description,
            updated_at=item.updated_at,
            updated_by=UserSummary.model_validate(item.updated_by) if item.updated_by else None,
        )
        for item in settings_service.list_settings(db)
    ]


@router.get("/settings", response_model=list[SettingRead], summary="Runtime thresholds")
def get_settings_(_: AdminUser, db: DbSession) -> list[SettingRead]:
    return _settings_read(db)


@router.put(
    "/settings",
    response_model=list[SettingRead],
    summary="Change runtime thresholds (applies immediately, no redeploy)",
)
def put_settings(data: SettingsUpdate, admin: AdminUser, db: DbSession) -> list[SettingRead]:
    settings_service.update_settings(db, admin, data.values)
    return _settings_read(db)
