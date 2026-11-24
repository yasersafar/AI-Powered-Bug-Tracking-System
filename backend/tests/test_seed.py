"""The demo seed must produce a consistent, demonstrable dataset (and refuse to double-seed)."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from scripts.seed import SeedError, run
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models import Bug, BugStatus, DeveloperProfile, Notification, User, UserRole

PASSWORD = "Seed#Pass1"


def test_seed_builds_demo_dataset(
    app: FastAPI, settings: Settings, db: Session, client: TestClient
) -> None:
    summary = run(app.state.session_factory, settings, PASSWORD)

    roles = set(db.scalars(select(User.role)))
    assert roles == set(UserRole)
    assert len(summary.projects) == 2
    assert db.scalar(select(func.count()).select_from(Bug)) == 50
    assert db.scalar(select(func.count()).select_from(Notification)) == 0

    # FR-22 demo: one developer with no history at all (cold start, alpha = 0) ...
    cold = db.scalars(select(DeveloperProfile).where(DeveloperProfile.resolved_count == 0)).all()
    assert len(cold) == 1 and cold[0].is_cold_start
    # ... one warm-starting developer and two experienced ones.
    assert summary.profiles == {
        "dana": (13, False),
        "omar": (10, False),
        "sara": (4, True),
        "leo": (0, True),
    }
    assert len(summary.duplicate_pairs) == 4
    closed_duplicate = db.scalar(select(Bug).where(Bug.duplicate_of_id.is_not(None)))
    assert closed_duplicate is not None and closed_duplicate.status == BugStatus.CLOSED

    # Timestamps are spread out and consistent.
    oldest = db.scalar(select(func.min(Bug.created_at)))
    newest = db.scalar(select(func.max(Bug.created_at)))
    assert oldest is not None and newest is not None and (newest - oldest).days >= 50
    assert db.scalar(select(func.count()).where(Bug.resolved_at < Bug.created_at)) == 0

    # The accounts work through the API with the seed password.
    login = client.post(
        "/api/v1/auth/login", data={"username": "pm@example.com", "password": PASSWORD}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    dashboard = client.get(
        f"/api/v1/projects/{summary.projects['Payments Platform']}/dashboard",
        params={"days": 60},
        headers=headers,
    ).json()
    assert dashboard["total_bugs"] == 28
    assert dashboard["average_resolution_hours"] > 0
    assert sum(day["created"] for day in dashboard["over_time"]) == 28


def test_seed_refuses_non_empty_database_and_production(app: FastAPI, settings: Settings) -> None:
    run(app.state.session_factory, settings, PASSWORD)
    with pytest.raises(SeedError):
        run(app.state.session_factory, settings, PASSWORD)
    run(app.state.session_factory, settings, PASSWORD, reset=True)  # explicit reset works
    with pytest.raises(SeedError):
        run(
            app.state.session_factory,
            settings.model_copy(update={"app_env": "production"}),
            PASSWORD,
        )
