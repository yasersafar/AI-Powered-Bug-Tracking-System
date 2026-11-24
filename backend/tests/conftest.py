"""Test fixtures. Integration tests run against a real PostgreSQL database.

The database is `<DATABASE_URL database>_test` unless TEST_DATABASE_URL is set. It is created
if missing and migrated with Alembic once per session; every test starts from empty tables.
"""

import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.security import hash_password
from app.main import create_app
from app.models import ProjectMember, ProjectRole, User, UserRole
from app.services.notification_service import OutgoingMessage, Transports

BACKEND_DIR = Path(__file__).resolve().parents[1]
PASSWORD = "Passw0rd!"
TABLES = (
    "notification",
    "system_setting",
    "model_state",
    "resolution_history",
    "bug_assignment",
    "profile_component",
    "profile_skill",
    "developer_profile",
    "audit_log",
    "attachment",
    "bug_embedding",
    "comment",
    "bug",
    "project_member",
    "project",
    '"user"',
)


def _test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


@pytest.fixture(scope="session")
def database_url() -> str:
    url = make_url(_test_database_url())
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": url.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    admin.dispose()

    rendered = url.render_as_string(hide_password=False)
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = rendered
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    return rendered


@pytest.fixture
def settings(database_url: str, tmp_path: Path) -> Settings:
    return Settings(
        app_env="test",
        database_url=database_url,
        jwt_secret_key="test-secret-key-not-for-production",
        bcrypt_rounds=4,
        attachment_dir=tmp_path / "attachments",
        login_rate_limit_attempts=1000,
        db_pool_size=2,
        db_max_overflow=2,
        ml_enabled=False,  # tests that need AI attach synthetic models (tests/test_ai.py)
    )


class RecordingSender:
    """Test double for ntfy/SMTP: records messages, can be told to fail."""

    def __init__(self) -> None:
        self.sent: list[OutgoingMessage] = []
        self.fail = False

    def send(self, message: OutgoingMessage) -> None:
        if self.fail:
            raise OSError("simulated outage")
        self.sent.append(message)


@dataclass
class Outbox:
    push: RecordingSender
    email: RecordingSender


@pytest.fixture
def outbox() -> Outbox:
    return Outbox(push=RecordingSender(), email=RecordingSender())


@pytest.fixture
def app(settings: Settings, outbox: Outbox) -> Iterator[FastAPI]:
    application = create_app(settings)
    application.state.notification_transports = Transports(push=outbox.push, email=outbox.email)
    yield application
    with application.state.engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY CASCADE"))
    application.state.engine.dispose()


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def db(app: FastAPI) -> Iterator[Session]:
    session: Session = app.state.session_factory()
    yield session
    session.close()


# --------------------------------------------------------------------------- helpers
@dataclass
class Actor:
    user: User
    headers: dict[str, str]

    @property
    def id(self) -> int:
        return self.user.id


class Factory:
    """Creates users/projects directly in the database and logs in through the API."""

    def __init__(self, client: TestClient, db: Session) -> None:
        self.client = client
        self.db = db
        self._n = 0

    def user(self, role: UserRole = UserRole.REPORTER, name: str | None = None) -> Actor:
        self._n += 1
        label = name or f"{role.value.lower()}{self._n}"
        user = User(
            email=f"{label}@example.com",
            full_name=label.title(),
            password_hash=hash_password(PASSWORD, rounds=4),
            role=role,
        )
        self.db.add(user)
        self.db.commit()
        return Actor(user=user, headers=self.login(user.email))

    def login(self, email: str, password: str = PASSWORD) -> dict[str, str]:
        response = self.client.post(
            "/api/v1/auth/login", data={"username": email, "password": password}
        )
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    def project(self, manager: Actor, name: str | None = None) -> int:
        self._n += 1
        response = self.client.post(
            "/api/v1/projects", json={"name": name or f"Project {self._n}"}, headers=manager.headers
        )
        assert response.status_code == 201, response.text
        return int(response.json()["id"])

    def member(self, project_id: int, actor: Actor, role: ProjectRole) -> None:
        self.db.add(ProjectMember(project_id=project_id, user_id=actor.id, role=role))
        self.db.commit()

    def bug(self, project_id: int, reporter: Actor, **overrides: object) -> dict[str, object]:
        payload: dict[str, object] = {
            "project_id": project_id,
            "title": "Editor crashes on save",
            "description": "Saving a file larger than 2 MB closes the editor without a message.",
            "steps_to_reproduce": "1. Open a 3 MB file\n2. Press Ctrl+S",
            "environment": "VS Code 1.105 on macOS 15",
            "components": ["editor"],
        }
        payload.update(overrides)
        response = self.client.post("/api/v1/bugs", json=payload, headers=reporter.headers)
        assert response.status_code == 201, response.text
        body: dict[str, object] = response.json()
        return body


@dataclass
class Team:
    """A project with one member per project role, plus an outsider and an administrator."""

    project_id: int
    manager: Actor
    developer: Actor
    developer2: Actor
    reporter: Actor
    outsider: Actor
    admin: Actor


@pytest.fixture
def factory(client: TestClient, db: Session) -> Factory:
    return Factory(client, db)


@pytest.fixture
def team(factory: Factory) -> Team:
    manager = factory.user(UserRole.PROJECT_MANAGER, "pat")
    developer = factory.user(UserRole.DEVELOPER, "dana")
    developer2 = factory.user(UserRole.DEVELOPER, "devon")
    reporter = factory.user(UserRole.REPORTER, "rita")
    outsider = factory.user(UserRole.DEVELOPER, "oscar")
    admin = factory.user(UserRole.ADMINISTRATOR, "ada")
    project_id = factory.project(manager, "Payments")
    factory.member(project_id, developer, ProjectRole.DEVELOPER)
    factory.member(project_id, developer2, ProjectRole.DEVELOPER)
    factory.member(project_id, reporter, ProjectRole.REPORTER)
    return Team(project_id, manager, developer, developer2, reporter, outsider, admin)
