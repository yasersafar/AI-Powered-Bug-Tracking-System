"""Triage endpoints and bug submission with AI (FR-10..FR-12, FR-22) and degradation (NFR-10).

The models attached here are SYNTHETIC test doubles (bag-of-words vectors and keyword rules):
they make the API behaviour testable without the trained artifacts. Model quality is measured
in docs/results, real-model latency in tests/test_nfr_perf.py.
"""

import hashlib
import time
from typing import Any, ClassVar

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from numpy.typing import NDArray
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BugEmbedding
from app.services.triage_service import TriageEngine
from ml.service.models import TriageModels
from ml.severity.model import SeverityPrediction
from tests.conftest import Factory, Team

B = "/api/v1/bugs"
AI = "/api/v1/ai"
VOCAB = ["crash", "save", "editor", "file", "theme", "login", "network", "payment", "card"]


class FakeEncoder:
    dimension = len(VOCAB)

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = np.array([[t.lower().count(w) for w in VOCAB] for t in texts], dtype=np.float32)
        norms = np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
        result: NDArray[np.float32] = (vectors / norms).astype(np.float32)
        return result


class FakeSeverity:
    labels: ClassVar[dict[str, str]] = {"crash": "Critical", "payment": "High", "theme": "Low"}

    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay, self.fail = delay, fail

    def predict(self, texts: list[str]) -> list[SeverityPrediction]:
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("simulated model failure")
        text = texts[0].lower()
        label = next((v for k, v in self.labels.items() if k in text), "Medium")
        return [SeverityPrediction(label, 0.8, {label: 0.8})]


def attach(app: FastAPI, **models: Any) -> TriageEngine:
    engine: TriageEngine = app.state.triage
    values: dict[str, Any] = {"encoder": FakeEncoder(), "severity": FakeSeverity()}
    values.update(models)
    engine.attach(TriageModels(**values), app.state.session_factory)
    return engine


FILLER = [
    ("Printing margins wrong", "The printed page margins are too wide in reports."),
    ("Font rendering blurry", "Fonts look blurry on high DPI screens in the sidebar."),
    ("Help page typo", "The help page has a typo in the second paragraph text."),
    ("Keyboard shortcut missing", "There is no keyboard shortcut for the export action."),
]


def add_filler(factory: Factory, team: Team) -> None:
    """Unrelated reports so BM25 has a realistic IDF (a 1-document index has none)."""
    for title, description in FILLER:
        factory.bug(team.project_id, team.reporter, title=title, description=description)


def profile(client: TestClient, team: Team, user_id: int, **fields: object) -> None:
    response = client.post(
        "/api/v1/admin/profiles", json={"user_id": user_id, **fields}, headers=team.admin.headers
    )
    assert response.status_code == 201, response.text


def resolve(client: TestClient, team: Team, bug_id: int, developer: Any) -> None:
    client.post(
        f"{B}/{bug_id}/assign", json={"assignee_id": developer.id}, headers=team.manager.headers
    )
    response = client.post(
        f"{B}/{bug_id}/transitions", json={"to_status": "Resolved"}, headers=developer.headers
    )
    assert response.status_code == 200, response.text


DUPLICATE = {
    "title": "Editor crash when I save a big file",
    "description": "The editor crash happens every time I save a file over 2 MB.",
}


# --------------------------------------------------------------------------- happy path
def test_submission_runs_the_shared_pipeline_and_indexes_the_bug(
    app: FastAPI, client: TestClient, factory: Factory, team: Team, db: Session
) -> None:
    profile(client, team, team.developer.id, skills=["editor", "files"], availability="Available")
    profile(client, team, team.developer2.id, skills=["editor", "crash", "save"])
    add_filler(factory, team)
    original = factory.bug(team.project_id, team.reporter)  # "Editor crashes on save" ...
    resolve(client, team, int(original["id"]), team.developer)
    engine = attach(app)
    assert engine.index is not None and engine.index.size(team.project_id) == 5  # warmed

    response = client.post(
        B,
        json={
            **DUPLICATE,
            "project_id": team.project_id,
            "steps_to_reproduce": "1. Save",
            "environment": "macOS",
            "components": ["editor"],
        },
        headers=team.reporter.headers,
    )
    assert response.status_code == 201, response.text
    bug = response.json()
    assert bug["ai_status"] == "ok"
    assert bug["severity"] == bug["predicted_severity"] == "Critical"
    assert bug["severity_confidence"] == 0.8
    assert bug["duplicate_candidates"][0]["bug_id"] == original["id"]
    assert bug["duplicate_candidates"][0]["title"] == original["title"]
    assert bug["ai_details"]["is_likely_duplicate"] is True
    assert bug["ai_details"]["notice"] is None
    assert {s["status"] for s in bug["ai_details"]["steps"].values()} == {"ok"}

    by_id = {r["developer_id"]: r for r in bug["recommended_developers"]}
    dana, devon = by_id[team.developer.id], by_id[team.developer2.id]
    # shared state: Dana fixed the original of this likely duplicate
    assert dana["notes"] == ["fixed the original of this likely duplicate"]
    assert "notes" in devon and devon["notes"] == []
    # FR-22: Devon has no resolved bugs -> alpha 0 and the cold-start reason
    assert (devon["alpha"], devon["reason"]) == (0.0, "new developer (cold start)")

    # FR-10: the new report is cached and searchable at once
    assert db.scalar(select(BugEmbedding).where(BugEmbedding.bug_id == bug["id"])) is not None
    found = client.post(
        f"{AI}/duplicates",
        json={"project_id": team.project_id, **DUPLICATE, "exclude_bug_id": original["id"]},
        headers=team.developer.headers,
    ).json()
    assert found["duplicates"][0]["bug_id"] == bug["id"]


def test_duplicates_while_typing_are_scoped_to_the_project(
    app: FastAPI, client: TestClient, factory: Factory, team: Team
) -> None:
    add_filler(factory, team)
    original = factory.bug(team.project_id, team.reporter)
    other_project = factory.project(team.manager, "Other")
    factory.bug(other_project, team.manager)  # identical text, other project
    attach(app)

    body = {"project_id": team.project_id, **DUPLICATE}
    response = client.post(f"{AI}/duplicates", json=body, headers=team.reporter.headers)
    assert response.status_code == 200, response.text
    data = response.json()
    assert [d["bug_id"] for d in data["duplicates"]] == [original["id"]]
    assert 0 < data["duplicates"][0]["score"] <= 1
    assert data["steps"]["duplicates"]["status"] == "ok"
    assert data["steps"]["severity"]["status"] == "skipped"
    assert data["severity"]["severity"] is None and data["recommendations"] == []

    excluded = client.post(
        f"{AI}/duplicates",
        json={**body, "exclude_bug_id": original["id"]},
        headers=team.reporter.headers,
    )
    assert excluded.json()["duplicates"] == []
    short = client.post(
        f"{AI}/duplicates",
        json={"project_id": team.project_id, "title": "ab"},
        headers=team.reporter.headers,
    )
    assert short.status_code == 422
    outsider = client.post(f"{AI}/duplicates", json=body, headers=team.outsider.headers)
    assert outsider.status_code in (403, 404)


def test_severity_triage_and_status_endpoints(app: FastAPI, client: TestClient, team: Team) -> None:
    attach(app)
    severity = client.post(
        f"{AI}/severity",
        json={"title": "Payment card declined", "description": "twice"},
        headers=team.reporter.headers,
    ).json()
    assert severity["severity"] == {
        "severity": "High",
        "confidence": 0.8,
        "probabilities": {"High": 0.8},
    }
    full = client.post(
        f"{AI}/triage",
        json={"project_id": team.project_id, "title": "Theme colours", "description": "wrong"},
        headers=team.reporter.headers,
    ).json()
    assert full["ai_status"] == "ok" and full["severity"]["severity"] == "Low"
    assert set(full["steps"]) == {"duplicates", "severity", "assignment"}
    assert len(full["recommendations"]) == 2 and full["total_ms"] > 0

    status = client.get(f"{AI}/status", headers=team.reporter.headers).json()
    assert status["state"] == "ready" and status["enabled"] is True
    assert status["models"]["severity"] == "loaded"
    served = {m["name"]: m for m in status["served_models"]}  # model_state rows
    assert served["severity"]["status"] == "loaded"
    assert served["assignment_history"]["status"] == "unavailable"
    assert served["severity"]["sha256"] is None  # synthetic model: no weight file
    assert client.get(f"{AI}/status").status_code == 401


def test_assign_uses_the_given_shared_state(
    app: FastAPI, client: TestClient, factory: Factory, team: Team
) -> None:
    profile(client, team, team.developer.id, availability="Unavailable")
    profile(client, team, team.developer2.id)
    original = factory.bug(team.project_id, team.reporter)
    resolve(client, team, int(original["id"]), team.developer2)
    attach(app)
    body = {"project_id": team.project_id, "title": "Something broke", "description": "badly"}

    critical = client.post(
        f"{AI}/assign", json={**body, "severity": "Critical"}, headers=team.manager.headers
    ).json()
    assert [r["developer_id"] for r in critical["recommendations"]] == [team.developer2.id]
    assert critical["steps"]["assignment"]["status"] == "ok"

    boosted = client.post(
        f"{AI}/assign",
        json={**body, "duplicate_of_ids": [original["id"]]},
        headers=team.manager.headers,
    ).json()
    top = boosted["recommendations"][0]
    assert top["developer_id"] == team.developer2.id and top["notes"]

    other = factory.bug(factory.project(team.manager, "Elsewhere"), team.manager)
    wrong = client.post(
        f"{AI}/assign",
        json={**body, "duplicate_of_ids": [other["id"]]},
        headers=team.manager.headers,
    )
    assert wrong.status_code == 404


def test_editing_the_text_refreshes_the_index(
    app: FastAPI, client: TestClient, factory: Factory, team: Team, db: Session
) -> None:
    add_filler(factory, team)
    engine = attach(app)
    bug = factory.bug(team.project_id, team.reporter)
    assert db.get(BugEmbedding, bug["id"]) is not None
    response = client.patch(
        f"{B}/{bug['id']}",
        json={
            "title": "Login fails on network change",
            "description": "Login fails every time the network changes on the laptop.",
        },
        headers=team.reporter.headers,
    )
    assert response.status_code == 200
    db.expire_all()
    assert db.get(BugEmbedding, bug["id"]) is None
    assert engine.index is not None and not engine.index.has_project(team.project_id)

    found = client.post(
        f"{AI}/duplicates",
        json={"project_id": team.project_id, "title": "network login", "description": "fails"},
        headers=team.reporter.headers,
    ).json()
    assert found["duplicates"][0]["bug_id"] == bug["id"]
    assert db.get(BugEmbedding, bug["id"]) is not None  # re-encoded on the next sync


# --------------------------------------------------------------------------- NFR-10
def submit(client: TestClient, team: Team) -> dict[str, Any]:
    response = client.post(
        B,
        json={
            **DUPLICATE,
            "project_id": team.project_id,
            "steps_to_reproduce": "1. Save",
            "environment": "macOS",
        },
        headers=team.reporter.headers,
    )
    assert response.status_code == 201, response.text  # the submission never fails
    body: dict[str, Any] = response.json()
    return body


def assert_unclassified(bug: dict[str, Any], notice_part: str) -> None:
    assert bug["severity"] == "Unclassified"
    assert bug["predicted_severity"] is None
    assert bug["ai_status"] == "degraded"
    assert notice_part in bug["ai_details"]["notice"]
    assert "Unclassified" in bug["ai_details"]["notice"]


def test_models_not_loaded(client: TestClient, team: Team) -> None:
    """ml_enabled=false (the test settings): the API works without any model."""
    bug = submit(client, team)
    assert_unclassified(bug, "not enabled")
    assert bug["duplicate_candidates"] == [] and bug["recommended_developers"] == []
    triage = client.post(
        f"{AI}/triage",
        json={"project_id": team.project_id, **DUPLICATE},
        headers=team.reporter.headers,
    ).json()
    assert triage["ai_status"] == "degraded"
    assert {s["status"] for s in triage["steps"].values()} == {"degraded"}


def test_admin_switches_ai_off_and_on(app: FastAPI, client: TestClient, team: Team) -> None:
    attach(app)
    settings = "/api/v1/admin/settings"
    off = client.put(settings, json={"values": {"ai_enabled": 0}}, headers=team.admin.headers)
    assert off.status_code == 200, off.text
    assert_unclassified(submit(client, team), "switched off")
    status = client.get(f"{AI}/status", headers=team.reporter.headers).json()
    assert status["enabled"] is False and status["state"] == "ready"

    client.put(settings, json={"values": {"ai_enabled": 1}}, headers=team.admin.headers)
    assert submit(client, team)["severity"] == "Critical"


def test_failing_severity_model_keeps_the_other_steps(
    app: FastAPI, client: TestClient, factory: Factory, team: Team
) -> None:
    add_filler(factory, team)
    original = factory.bug(team.project_id, team.reporter)
    attach(app, severity=FakeSeverity(fail=True))
    bug = submit(client, team)
    assert_unclassified(bug, "severity")
    assert bug["duplicate_candidates"][0]["bug_id"] == original["id"]  # duplicates still ran
    steps = bug["ai_details"]["steps"]
    assert steps["severity"] == {
        "status": "degraded",
        "elapsed_ms": steps["severity"]["elapsed_ms"],
        "detail": "failed: RuntimeError",
    }
    assert steps["duplicates"]["status"] == steps["assignment"]["status"] == "ok"


def test_slow_severity_model_times_out(app: FastAPI, client: TestClient, team: Team) -> None:
    attach(app, severity=FakeSeverity(delay=1.0))
    client.put(
        "/api/v1/admin/settings",
        json={"values": {"severity_timeout_ms": 100}},
        headers=team.admin.headers,
    )
    started = time.perf_counter()
    bug = submit(client, team)
    assert time.perf_counter() - started < 0.9  # did not wait for the model
    assert_unclassified(bug, "severity")
    assert "timed out after 100 ms" in bug["ai_details"]["steps"]["severity"]["detail"]


def test_missing_severity_artifact(app: FastAPI, client: TestClient, team: Team) -> None:
    attach(app, severity=None, errors={"severity": "unavailable: eclipse.joblib missing"})
    bug = submit(client, team)
    assert_unclassified(bug, "severity")
    assert "eclipse.joblib" in bug["ai_details"]["steps"]["severity"]["detail"]


def test_pipeline_crash_still_saves_the_bug(
    app: FastAPI, client: TestClient, team: Team, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = attach(app)

    def boom(*args: object, **kwargs: object) -> None:
        raise MemoryError("simulated crash")

    assert engine.pipeline is not None
    monkeypatch.setattr(engine.pipeline, "run", boom)
    assert_unclassified(submit(client, team), "failed (MemoryError)")


def test_loading_and_failed_states(app: FastAPI, client: TestClient, team: Team) -> None:
    engine: TriageEngine = app.state.triage
    engine.state = "loading"
    assert_unclassified(submit(client, team), "still loading")
    engine.state, engine.error = "failed", "OSError: disk"
    assert_unclassified(submit(client, team), "could not be loaded")
    status = client.get(f"{AI}/status", headers=team.reporter.headers).json()
    assert (status["state"], status["error"]) == ("failed", "OSError: disk")


def test_model_state_records_the_served_artifact(app: FastAPI, db: Session, tmp_path: Any) -> None:
    from app.models import ModelState
    from app.services.triage_service import record_model_state

    weights = tmp_path / "severity" / "eclipse.joblib"
    weights.parent.mkdir()
    weights.write_bytes(b"synthetic weights")
    models = TriageModels(
        encoder=FakeEncoder(), severity=FakeSeverity(), files={"severity": weights}
    )
    record_model_state(db, models, tmp_path)
    row = db.get(ModelState, "severity")
    assert row is not None and row.status == "loaded"
    assert row.artifact == "severity/eclipse.joblib" and row.size_bytes == 17
    assert row.sha256 == hashlib.sha256(b"synthetic weights").hexdigest()
