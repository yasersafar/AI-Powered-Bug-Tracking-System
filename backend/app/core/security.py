from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings


def hash_password(password: str) -> str:
    """Turn a plain password into a bcrypt hash for safe storage."""
    pw = password.encode("utf-8")[:72]  # bcrypt only uses the first 72 bytes
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain password against the stored hash."""
    pw = plain_password.encode("utf-8")[:72]
    return bcrypt.checkpw(pw, hashed_password.encode("utf-8"))


def create_access_token(subject: str) -> str:
    """Make a signed JWT that proves who the user is, valid for 8 hours."""
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Read a token back, checking its signature and expiry. Raises on failure."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
