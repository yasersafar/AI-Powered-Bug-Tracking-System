"""Password hashing (bcrypt, NFR-04) and JWT access tokens (FR-02)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import Settings

BCRYPT_MAX_BYTES = 72  # bcrypt ignores (bcrypt>=5 rejects) anything beyond 72 bytes


def hash_password(password: str, rounds: int = 12) -> str:
    """Salted bcrypt hash. Callers validate the 72-byte limit before hashing."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=rounds)).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    encoded = password.encode("utf-8")
    if len(encoded) > BCRYPT_MAX_BYTES:
        return False
    try:
        return bcrypt.checkpw(encoded, password_hash.encode("ascii"))
    except ValueError:
        return False


# A real hash of a random string: used to spend the same time on unknown e-mails as on
# known ones, so login timing does not reveal which addresses are registered.
_DUMMY_HASH = hash_password("timing-equaliser-not-a-real-password", rounds=12)


def burn_password_check(password: str) -> None:
    verify_password(password, _DUMMY_HASH)


def create_access_token(
    user_id: int, settings: Settings, token_version: int = 0, now: datetime | None = None
) -> str:
    issued_at = now or datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "ver": token_version,
        "iat": int(issued_at.timestamp()),
        "exp": int((issued_at + timedelta(minutes=settings.jwt_expire_minutes)).timestamp()),
        "type": "access",
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    """Verify signature and expiry. Raises `jwt.PyJWTError` when the token is not valid."""
    payload: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["sub", "exp", "iat", "ver"]},
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return payload
