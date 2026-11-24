"""Liveness endpoint used by Docker healthchecks and the extension status bar (NFR-09)."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import Settings, get_settings

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    """Liveness answer of GET /health (NFR-09)."""

    status: Literal["ok"] = Field(description="Always `ok` when the process is serving requests.")
    version: str = Field(description="Backend version.", examples=["0.1.0"])
    environment: str = Field(description="Deployment environment.", examples=["development"])


@router.get("/health", response_model=HealthResponse, summary="Liveness check")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    return HealthResponse(status="ok", version=settings.app_version, environment=settings.app_env)
