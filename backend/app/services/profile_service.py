"""Admin-managed developer profiles (FR-20). Every change is audited against the profile."""

from collections.abc import Sequence
from typing import TypeVar

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError
from app.models import DeveloperProfile, ProfileComponent, ProfileSkill, User, UserRole
from app.schemas.admin import ProfileCreate, ProfileUpdate
from app.services import audit_service, developer_activity, settings_service
from app.services.access import not_found

_LOAD = (
    selectinload(DeveloperProfile.user),
    selectinload(DeveloperProfile.skill_rows),
    selectinload(DeveloperProfile.component_rows),
)


def get_profile(db: Session, profile_id: int) -> DeveloperProfile:
    profile = db.scalar(
        select(DeveloperProfile).where(DeveloperProfile.id == profile_id).options(*_LOAD)
    )
    if profile is None:
        raise not_found("Developer profile")
    return profile


def list_profiles(
    db: Session, active: bool | None, cold_start: bool | None
) -> Sequence[DeveloperProfile]:
    query = select(DeveloperProfile).join(User, User.id == DeveloperProfile.user_id).options(*_LOAD)
    if active is not None:
        query = query.where(DeveloperProfile.active.is_(active))
    if cold_start is not None:
        query = query.where(DeveloperProfile.is_cold_start.is_(cold_start))
    return db.scalars(query.order_by(User.full_name)).all()


Row = TypeVar("Row", ProfileSkill, ProfileComponent)


def _sync(rows: list[Row], values: list[str], attr: str, factory: type[Row]) -> list[Row]:
    """Keep rows whose value stays, drop the rest, add new ones (avoids unique-key clashes)."""
    kept = [row for row in rows if getattr(row, attr) in values]
    present = {getattr(row, attr) for row in kept}
    return kept + [factory(**{attr: v}) for v in values if v not in present]


def _apply(
    db: Session, admin: User, profile: DeveloperProfile, data: ProfileCreate | ProfileUpdate
) -> None:
    fields = data.model_dump(exclude_unset=True, exclude={"user_id"})
    for name, value in fields.items():
        if value is None:
            continue
        if name == "skills":
            old = profile.skills
            if old != value:
                profile.skill_rows = _sync(profile.skill_rows, value, "skill", ProfileSkill)
        elif name == "components":
            old = profile.components
            if old != value:
                profile.component_rows = _sync(
                    profile.component_rows, value, "component", ProfileComponent
                )
        else:
            old = getattr(profile, name)
            if old != value:
                setattr(profile, name, value)
        if old != value and profile.id is not None:
            audit_service.record(
                db, admin, "profile_updated", profile_id=profile.id, field=name, old=old, new=value
            )


def create_profile(db: Session, admin: User, data: ProfileCreate) -> DeveloperProfile:
    user = db.get(User, data.user_id)
    if user is None:
        raise not_found("User")
    if user.role != UserRole.DEVELOPER:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "not_a_developer",
            "Developer profiles can only be created for users with the Developer role",
        )
    if db.scalar(select(DeveloperProfile.id).where(DeveloperProfile.user_id == user.id)):
        raise AppError(
            status.HTTP_409_CONFLICT, "profile_exists", "This user already has a profile"
        )

    threshold = int(settings_service.get_value(db, "cold_start_threshold"))
    resolved = developer_activity.resolved_count(db, user.id)
    profile = DeveloperProfile(
        user_id=user.id, resolved_count=resolved, is_cold_start=resolved < threshold
    )
    _apply(db, admin, profile, data)
    db.add(profile)
    db.flush()
    audit_service.record(
        db, admin, "profile_created", profile_id=profile.id, new=audit_service.user_label(user)
    )
    db.commit()
    return get_profile(db, profile.id)


def update_profile(
    db: Session, admin: User, profile: DeveloperProfile, data: ProfileUpdate
) -> DeveloperProfile:
    _apply(db, admin, profile, data)
    db.commit()
    return get_profile(db, profile.id)
