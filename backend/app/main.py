"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api import (
    admin,
    ai,
    attachments,
    auth,
    bugs,
    comments,
    health,
    notifications,
    projects,
    users,
)
from app.core.config import Settings, get_settings
from app.core.database import build_engine, build_session_factory
from app.core.errors import register_error_handlers
from app.core.rate_limit import SlidingWindowLimiter
from app.services.notification_service import Transports
from app.services.triage_service import TriageEngine

API_TAGS = [
    {"name": "health", "description": "Liveness check (NFR-09)."},
    {"name": "auth", "description": "Registration and login (FR-01, FR-02)."},
    {"name": "users", "description": "Own profile and user administration (FR-03, FR-04)."},
    {"name": "projects", "description": "Projects and team membership (FR-18, FR-19)."},
    {"name": "bugs", "description": "Bug submission, lifecycle, search and audit trail."},
    {"name": "comments", "description": "Flat, chronological comments (FR-09)."},
    {"name": "attachments", "description": "Bug attachments (FR-14)."},
    {
        "name": "ai",
        "description": "Triage pipeline: duplicates, severity, developer recommendation "
        "(FR-10..FR-12, FR-22). Degrades instead of failing (NFR-10).",
    },
    {"name": "notifications", "description": "In-app alerts and push subscription (FR-16, FR-17)."},
    {
        "name": "admin",
        "description": "Developer profiles, developer tracking and runtime settings "
        "(FR-20, FR-21, NFR-14). Administrator only.",
    },
]

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    logging.basicConfig(
        level=settings.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.triage.start(app.state.session_factory)  # background: API is usable at once
        yield
        app.state.triage.shutdown()
        app.state.engine.dispose()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "REST API for the AI-Powered Bug Tracking System: bug lifecycle management plus "
            "an integrated triage pipeline (duplicate detection, severity classification, "
            "developer assignment). All business routes are under `/api/v1`.\n\n"
            "Errors always have the shape `{code, message, details}`."
        ),
        openapi_tags=API_TAGS,
        lifespan=lifespan,
    )

    # Stateless backend (NFR-08): the only per-process state is the pooled engine and the
    # login rate-limit counters.
    engine = build_engine(settings)
    app.state.engine = engine
    app.state.session_factory = build_session_factory(engine)
    app.state.notification_transports = Transports.from_settings(settings)
    app.state.triage = TriageEngine(settings)
    app.state.login_limiter = SlidingWindowLimiter(
        settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
    )
    # Every `Depends(get_settings)` resolves to the settings this app was built with,
    # so tests can build isolated apps with their own configuration.
    app.dependency_overrides[get_settings] = lambda: settings
    app.state.settings = settings

    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    @app.middleware("http")
    async def security_headers(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        for name, value in SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
        return response

    register_error_handlers(app)
    app.include_router(health.router)
    for router in (
        auth.router,
        users.router,
        projects.router,
        bugs.router,
        comments.router,
        attachments.router,
        ai.router,
        notifications.router,
        admin.router,
    ):
        app.include_router(router, prefix=settings.api_prefix)
    return app


app = create_app()
