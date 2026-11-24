"""FastAPI dependencies: database session, current user, global-role checks (FR-03, NFR-06)."""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.database import get_db
from app.core.errors import AppError
from app.core.security import decode_access_token
from app.models import User, UserRole
from app.services.triage_service import TriageEngine

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[Settings, Depends(get_settings)]


def get_triage(request: Request) -> TriageEngine:
    engine: TriageEngine = request.app.state.triage
    return engine


Triage = Annotated[TriageEngine, Depends(get_triage)]


def _unauthorized(message: str = "Not authenticated") -> AppError:
    return AppError(status.HTTP_401_UNAUTHORIZED, "unauthorized", message)


def get_current_user(
    db: DbSession,
    settings: AppSettings,
    token: Annotated[str | None, Depends(oauth2_scheme)],
) -> User:
    if not token:
        raise _unauthorized()
    try:
        payload = decode_access_token(token, settings)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise _unauthorized("Invalid or expired token") from exc

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise _unauthorized("Invalid or expired token")
    if payload.get("ver") != user.token_version:
        raise _unauthorized("Token was revoked, please log in again")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_global_role(*roles: UserRole) -> Callable[[User], User]:
    """Dependency factory: only users whose global role is listed may continue (else 403)."""

    def checker(user: CurrentUser) -> User:
        if user.role not in roles:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                "forbidden",
                "Your role does not allow this action",
                {"required_roles": [r.value for r in roles]},
            )
        return user

    return checker
