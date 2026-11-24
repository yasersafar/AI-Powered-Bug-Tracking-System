"""Application settings, read from environment variables (and `.env` in local runs).

Runtime-tunable thresholds (NFR-14) are NOT kept here: they live in the
`system_setting` table so an Administrator can change them without a redeploy.
This module only holds deployment-level configuration.
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# <repo>/backend/app/core/config.py -> parents[3] is <repo>
_REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_REPO_ROOT / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "AI-Powered Bug Tracking System"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    log_level: str = "INFO"
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://bugtracker:change-me@localhost:5432/bugtracker"
    # NFR-08: connection pooling
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_pool_timeout_seconds: int = 10
    db_echo: bool = False

    # HS256 keys shorter than 32 bytes are rejected (RFC 7518 section 3.2).
    jwt_secret_key: str = Field(default="dev-only-insecure-key-change-me-0123456789", min_length=32)
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480  # FR-02: fixed 8-hour expiry
    # NFR-04: bcrypt work factor (tests lower it to keep the suite fast)
    bcrypt_rounds: int = Field(default=12, ge=4, le=16)

    # Brute-force protection on /auth/login (per client IP, sliding window)
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 60

    # NoDecode: accept a plain comma-separated string instead of JSON.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)

    attachment_dir: Path = _REPO_ROOT / "backend" / "storage" / "attachments"
    attachment_max_bytes: int = 10 * 1024 * 1024  # FR-05 / FR-14: 10 MB

    ntfy_base_url: str = "http://localhost:8080"
    ntfy_publish_url: str = "http://localhost:8080"
    ntfy_topic_prefix: str = Field(default="bugtracker", pattern=r"^[A-Za-z0-9_-]{1,20}$")
    # Access token of the publish-only ntfy account (see docker-compose.yml)
    ntfy_publish_token: str = ""
    notification_timeout_seconds: float = 5.0

    smtp_host: str = "localhost"
    smtp_port: int = 1025
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_tls: bool = False
    smtp_from: str = "Bug Tracker <no-reply@bugtracker.local>"

    # Triage pipeline (FR-10..FR-12). Models run in-process on CPU and are loaded from
    # local files only (DC-03). ml_enabled=false starts the API without them: every bug is
    # then saved as Unclassified (NFR-10). Admins can also switch AI off at runtime.
    ml_enabled: bool = True
    ml_artifacts_dir: Path = _REPO_ROOT / "ml" / "artifacts"
    ml_threads: int = Field(default=2, ge=1, le=16)  # BLAS/torch threads used for inference
    ml_workers: int = Field(default=8, ge=1, le=64)  # concurrent triage steps

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @field_validator("ntfy_base_url", "ntfy_publish_url")
    @classmethod
    def _forbid_public_ntfy(cls, value: str) -> str:
        # DC-03: bug text must never be sent to the public ntfy.sh instance.
        host = value.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower()
        if host == "ntfy.sh" or host.endswith(".ntfy.sh"):
            raise ValueError(
                "The public ntfy.sh server is not allowed (DC-03); use self-hosted ntfy"
            )
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
