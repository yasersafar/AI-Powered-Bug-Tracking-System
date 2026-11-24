"""Registration, login, profile and account administration (FR-01..FR-04)."""

from fastapi import status
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.errors import AppError
from app.core.security import burn_password_check, hash_password, verify_password
from app.models import User, UserRole
from app.schemas.user import AdminUserUpdate, RegisterRequest, UpdateMeRequest
from app.services import audit_service


def normalize_email(email: str) -> str:
    return email.strip().lower()


def get_by_email(db: Session, email: str) -> User | None:
    return db.scalar(select(User).where(User.email == normalize_email(email)))


def register(db: Session, data: RegisterRequest, settings: Settings) -> User:
    email = normalize_email(data.email)
    if get_by_email(db, email) is not None:
        raise AppError(status.HTTP_409_CONFLICT, "email_taken", "This e-mail is already registered")
    user = User(
        email=email,
        full_name=data.full_name,
        password_hash=hash_password(data.password, settings.bcrypt_rounds),
        role=UserRole.REPORTER,
    )
    db.add(user)
    try:
        db.commit()
    except IntegrityError as exc:  # concurrent registration with the same e-mail
        db.rollback()
        raise AppError(
            status.HTTP_409_CONFLICT, "email_taken", "This e-mail is already registered"
        ) from exc
    db.refresh(user)
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = get_by_email(db, email)
    if user is None:
        burn_password_check(password)
        return None
    if not verify_password(password, user.password_hash) or not user.is_active:
        return None
    return user


def update_me(db: Session, user: User, data: UpdateMeRequest) -> User:
    for name, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(user, name, value)
    db.commit()
    db.refresh(user)
    return user


def change_password(
    db: Session, user: User, current_password: str, new_password: str, settings: Settings
) -> User:
    if not verify_password(current_password, user.password_hash):
        raise AppError(
            status.HTTP_400_BAD_REQUEST, "wrong_password", "Current password is incorrect"
        )
    user.password_hash = hash_password(new_password, settings.bcrypt_rounds)
    user.token_version += 1  # every token issued so far stops working
    audit_service.record(db, user, "password_changed", target_user_id=user.id)
    db.commit()
    db.refresh(user)
    return user


def search_users(
    db: Session, q: str | None, page: int, page_size: int, active_only: bool
) -> tuple[list[User], int]:
    query = select(User)
    if q:
        pattern = f"%{q.lower()}%"
        query = query.where(
            or_(func.lower(User.email).like(pattern), func.lower(User.full_name).like(pattern))
        )
    if active_only:
        query = query.where(User.is_active.is_(True))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    users = db.scalars(
        query.order_by(User.full_name, User.id).offset((page - 1) * page_size).limit(page_size)
    ).all()
    return list(users), total


def admin_update(db: Session, admin: User, target: User, data: AdminUserUpdate) -> User:
    if target.id == admin.id:
        raise AppError(
            status.HTTP_409_CONFLICT,
            "self_change",
            "Administrators cannot change their own role or deactivate themselves",
        )
    if data.role is not None and data.role != target.role:
        audit_service.record(
            db,
            admin,
            "role_changed",
            target_user_id=target.id,
            field="role",
            old=target.role.value,
            new=data.role.value,
        )
        target.role = data.role
    if data.is_active is not None and data.is_active != target.is_active:
        audit_service.record(
            db,
            admin,
            "activation_changed",
            target_user_id=target.id,
            field="is_active",
            old=target.is_active,
            new=data.is_active,
        )
        target.is_active = data.is_active
    db.commit()
    db.refresh(target)
    return target
