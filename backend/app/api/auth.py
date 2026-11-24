"""Registration and login (FR-01, FR-02)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import AppSettings, DbSession
from app.core.errors import AppError, ErrorResponse
from app.core.security import create_access_token
from app.schemas.user import RegisterRequest, TokenResponse, UserMe, UserRead
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new account (role: Reporter)",
    responses={409: {"model": ErrorResponse, "description": "E-mail already registered"}},
)
def register(data: RegisterRequest, db: DbSession, settings: AppSettings) -> UserRead:
    return UserRead.model_validate(user_service.register(db, data, settings))


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Log in and receive an 8-hour bearer token",
    description=(
        "OAuth2 password flow: send `username` (the e-mail) and `password` as form fields. "
        "Rate limited per client IP."
    ),
    responses={
        401: {"model": ErrorResponse, "description": "Wrong e-mail or password"},
        429: {"model": ErrorResponse, "description": "Too many login attempts"},
    },
)
def login(
    request: Request,
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: DbSession,
    settings: AppSettings,
) -> TokenResponse:
    client_ip = request.client.host if request.client else "unknown"
    retry_after = request.app.state.login_limiter.hit(f"login:{client_ip}")
    if retry_after is not None:
        raise AppError(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too_many_requests",
            "Too many login attempts, try again later",
            {"retry_after_seconds": round(retry_after)},
        )
    user = user_service.authenticate(db, form.username, form.password)
    if user is None:
        raise AppError(
            status.HTTP_401_UNAUTHORIZED, "invalid_credentials", "Wrong e-mail or password"
        )
    return TokenResponse(
        access_token=create_access_token(user.id, settings, user.token_version),
        expires_in=settings.jwt_expire_minutes * 60,
        user=UserMe.model_validate(user),
    )
