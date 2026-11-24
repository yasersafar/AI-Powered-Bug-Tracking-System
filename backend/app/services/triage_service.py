"""Bridge between the API and the in-process triage pipeline (ml.service).

* Loads the models in a background thread at start-up, so the API is usable immediately;
  until they are ready every triage is `degraded` and bugs are saved as Unclassified (NFR-10).
* Keeps the per-project duplicate index in sync with the database. Embeddings are cached in
  `bug_embedding`, so a restart only re-tokenises reports instead of re-encoding them.
* Builds the TriageContext from the database (runtime thresholds, project developers with
  their profiles, workload and resolved bugs) and turns the TriageResult into API data.

Nothing in here may break a bug submission: every failure becomes a degraded result.
"""

import hashlib
import logging
import os
import socket
import threading
import time
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import (
    AiStatus,
    Bug,
    BugEmbedding,
    BugStatus,
    DeveloperProfile,
    ModelState,
    ProjectMember,
    ProjectRole,
    ResolutionHistory,
    Severity,
    User,
)
from app.services import settings_service
from ml.common.text import clean_text, report_text
from ml.duplicate.detector import DuplicateCandidate
from ml.service.context import (
    ALL_STEPS_ORDER,
    ASSIGNMENT,
    DUPLICATES,
    EMBED_CHARS,
    SEVERITY,
    DeveloperInfo,
    StepReport,
    StepStatus,
    TriageContext,
    TriageResult,
    TriageSettings,
)
from ml.service.index import BugIndex
from ml.service.models import TriageModels, load_models
from ml.service.pipeline import TriagePipeline

logger = logging.getLogger("app.triage")

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
ENCODE_BATCH = 256
RESOLVED_PER_DEVELOPER = 50  # most recent resolutions used as history evidence
ACTIVE = (BugStatus.OPEN, BugStatus.IN_PROGRESS)

NOTICE_OFF = "AI triage is switched off by an administrator."
NOTICE_LOADING = "AI models are still loading."
NOTICE_DISABLED = "AI triage is not enabled on this server."
NOTICE_SEVERITY = (
    "Severity could not be predicted, so the bug is saved as Unclassified. "
    "A Developer or Project Manager can set it."
)


@dataclass
class AiOutcome:
    """What a triage run produced, ready to store on a bug or return from /ai/*."""

    ai_status: AiStatus
    severity: Severity | None = None
    confidence: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    duplicates: list[dict[str, Any]] = field(default_factory=list)
    is_likely_duplicate: bool = False
    recommendations: list[dict[str, Any]] = field(default_factory=list)
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_ms: float = 0.0
    notice: str | None = None
    vector: NDArray[np.float32] | None = None

    @property
    def details(self) -> dict[str, Any]:
        return {
            "steps": self.steps,
            "total_ms": self.total_ms,
            "is_likely_duplicate": self.is_likely_duplicate,
            "notice": self.notice,
        }


class TriageEngine:
    """Models + duplicate index + pipeline for one application instance."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = "loading" if settings.ml_enabled else "disabled"
        self.error: str | None = None
        self.models: TriageModels | None = None
        self.index: BugIndex | None = None
        self.pipeline: TriagePipeline | None = None
        self._sync_locks: dict[int, threading.Lock] = defaultdict(threading.Lock)
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ lifecycle
    @property
    def ready(self) -> bool:
        return self.state == "ready" and self.pipeline is not None

    def start(self, session_factory: sessionmaker[Session]) -> None:
        """Load models and warm the index without blocking start-up."""
        if not self.settings.ml_enabled or self._thread is not None:
            return

        def work() -> None:
            try:
                models = load_models(
                    self.settings.ml_artifacts_dir,
                    self.settings.ml_threads,
                    database_name(self.settings),
                )
                self.attach(models, session_factory)
            except Exception as exc:
                logger.exception("triage engine failed to start")
                self.state, self.error = "failed", f"{type(exc).__name__}: {exc}"

        self._thread = threading.Thread(target=work, name="triage-loader", daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float) -> bool:
        if self._thread is not None:
            self._thread.join(timeout)
        return self.ready

    def attach(self, models: TriageModels, session_factory: sessionmaker[Session]) -> None:
        """Install loaded models (also used by tests with synthetic models)."""
        dimension = getattr(models.encoder, "dimension", 384)
        encoder = models.encoder.encode if models.encoder is not None else _no_encoder
        self.models = models
        self.index = BugIndex(encoder, dimension=dimension)
        self.pipeline = TriagePipeline(models, self.index, workers=self.settings.ml_workers)
        started = time.perf_counter()
        with session_factory() as db:
            record_model_state(db, models, self.settings.ml_artifacts_dir)
            for project_id in db.scalars(select(Bug.project_id).distinct()):
                self.sync_project(db, project_id)
        logger.info(
            "duplicate index warmed: %d reports in %.1fs",
            self.index.size(),
            time.perf_counter() - started,
        )
        self.state = "ready"

    def shutdown(self) -> None:
        if self.pipeline is not None:
            self.pipeline.shutdown()

    def status(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "error": self.error,
            "models": self.models.describe() if self.models else {},
            "load_seconds": self.models.load_seconds if self.models else None,
            "indexed_reports": self.index.size() if self.index else 0,
        }

    # ------------------------------------------------------------------ duplicate index
    def sync_project(self, db: Session, project_id: int) -> None:
        """Make sure every report of the project is in the index (incremental)."""
        if self.index is None:
            return
        with self._sync_locks[project_id]:
            after = self.index.max_bug_id(project_id) if self.index.has_project(project_id) else 0
            rows = db.execute(
                select(Bug.id, Bug.title, Bug.description, BugEmbedding.vector, BugEmbedding.model)
                .outerjoin(BugEmbedding, BugEmbedding.bug_id == Bug.id)
                .where(Bug.project_id == project_id, Bug.id > after)
                .order_by(Bug.id)
            ).all()
            if not rows:
                return
            ids = [r.id for r in rows]
            texts = [report_text(r.title, r.description) for r in rows]
            vectors = np.zeros((len(rows), self.index.dimension), dtype=np.float32)
            missing: list[int] = []
            for i, row in enumerate(rows):
                if row.vector is not None and row.model == EMBEDDING_MODEL:
                    vectors[i] = np.frombuffer(row.vector, dtype=np.float32)
                else:
                    missing.append(i)
            if missing:
                if self.models is None or self.models.encoder is None:
                    keep = [i for i in range(len(rows)) if i not in set(missing)]
                    ids, texts, vectors = (
                        [ids[i] for i in keep],
                        [texts[i] for i in keep],
                        vectors[keep],
                    )
                else:
                    encoded = self._encode([clean_text(texts[i], EMBED_CHARS) for i in missing])
                    vectors[missing] = encoded
                    self._store(db, [(ids[i], encoded[j]) for j, i in enumerate(missing)])
            self.index.add_many(project_id, ids, texts, vectors)

    def _encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        assert self.models is not None and self.models.encoder is not None  # noqa: S101
        chunks = [
            self.models.encoder.encode(list(texts[i : i + ENCODE_BATCH]))
            for i in range(0, len(texts), ENCODE_BATCH)
        ]
        return np.vstack(chunks).astype(np.float32)

    def _store(self, db: Session, items: Iterable[tuple[int, NDArray[np.float32]]]) -> None:
        for bug_id, vector in items:
            db.merge(
                BugEmbedding(
                    bug_id=bug_id,
                    model=EMBEDDING_MODEL,
                    dimension=int(vector.shape[0]),
                    vector=np.asarray(vector, dtype=np.float32).tobytes(),
                )
            )
        db.commit()

    def index_bug(self, db: Session, bug: Bug, vector: NDArray[np.float32] | None) -> None:
        """Add a newly created report to the index (FR-10: incremental update)."""
        if not self.ready or self.index is None:
            return
        try:
            if vector is None:  # triage produced no embedding: encode now (if possible)
                if self.models is None or self.models.encoder is None:
                    return
                text = clean_text(report_text(bug.title, bug.description), EMBED_CHARS)
                self._store(db, [(bug.id, self._encode([text])[0])])
            # (with a vector, create_bug already saved it in the bug's own transaction)
            self.sync_project(db, bug.project_id)  # also picks up reports from other workers
        except Exception:
            db.rollback()
            logger.exception("could not index bug %s", bug.id)

    def forget_text(self, db: Session, bug: Bug) -> None:
        """A report's text changed: drop its cached embedding; the index is rebuilt lazily."""
        try:
            db.query(BugEmbedding).filter(BugEmbedding.bug_id == bug.id).delete()
            db.commit()
            if self.index is not None:
                self.index.drop_project(bug.project_id)
        except Exception:
            db.rollback()
            logger.exception("could not reset the embedding of bug %s", bug.id)

    # ------------------------------------------------------------------ triage
    def run(
        self,
        db: Session,
        *,
        project_id: int,
        title: str,
        description: str,
        components: Sequence[str] = (),
        steps: Sequence[str] = ALL_STEPS_ORDER,
        exclude_bug_ids: Iterable[int] = (),
        severity_hint: Severity | None = None,
        duplicate_hint: Sequence[int] = (),
    ) -> AiOutcome:
        """Run (part of) the pipeline. Never raises: problems become a degraded outcome."""
        try:
            values = settings_service.get_values(db)
            if not int(values["ai_enabled"]):
                return _unavailable(steps, NOTICE_OFF)
            if not self.ready or self.pipeline is None:
                notice = NOTICE_DISABLED if self.state == "disabled" else NOTICE_LOADING
                if self.state == "failed":
                    notice = "AI models could not be loaded."
                return _unavailable(steps, notice)

            if DUPLICATES in steps or ASSIGNMENT in steps:
                self.sync_project(db, project_id)
            ctx = TriageContext(
                title=title,
                description=description,
                project_id=project_id,
                components=list(components),
                settings=_triage_settings(values),
                developers=load_developers(db, project_id) if ASSIGNMENT in steps else (),
                exclude_bug_ids=frozenset(exclude_bug_ids),
            )
            if severity_hint is not None and SEVERITY not in steps:
                ctx.severity = severity_hint.value
            if duplicate_hint and DUPLICATES not in steps:
                ctx.duplicate_candidates = [
                    DuplicateCandidate(b, 1.0, 1.0, 0.0) for b in duplicate_hint
                ]
                ctx.is_likely_duplicate = True
            # Give the database connection back to the pool while the models run, so
            # concurrent submissions do not exhaust the pool (NFR-03).
            db.commit()
            result = self.pipeline.run(ctx, steps)
            return _outcome(db, result, steps)
        except Exception as exc:
            db.rollback()
            logger.exception("triage failed")
            return _unavailable(steps, f"AI triage failed ({type(exc).__name__}).")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def record_model_state(db: Session, models: TriageModels, artifacts: Path) -> None:
    """Upsert one `model_state` row per model: status, weight file and its SHA-256."""
    loaded = {
        "embedding": models.encoder,
        "severity": models.severity,
        "assignment_history": models.history,
    }
    worker = f"{socket.gethostname()}:{os.getpid()}"[:120]
    try:
        for name, model in loaded.items():
            found = models.files.get(name)
            path = found if found is not None and found.exists() else None
            row = db.get(ModelState, name) or ModelState(name=name)
            row.status = "loaded" if model is not None else "unavailable"
            row.detail = None if model is not None else models.errors.get(name)
            if path is None:
                row.artifact, row.sha256, row.size_bytes = None, None, None
            else:
                shown = path.relative_to(artifacts) if path.is_relative_to(artifacts) else path
                row.artifact = str(shown)
                row.sha256 = _sha256(path)
                row.size_bytes = path.stat().st_size
            row.loaded_by = worker
            row.loaded_at = datetime.now(UTC)
            db.add(row)
        db.commit()
    except Exception:  # bookkeeping must never stop the models from serving
        db.rollback()
        logger.exception("could not record model_state")


def model_states(db: Session) -> list[ModelState]:
    return list(db.scalars(select(ModelState).order_by(ModelState.name)))


def database_name(settings: Settings) -> str:
    """Live assignment models are stored per database (their classes are user ids)."""
    return str(make_url(settings.database_url).database or "default")


def _no_encoder(texts: list[str]) -> NDArray[np.float32]:
    raise RuntimeError("embedding model not loaded")


def _triage_settings(values: dict[str, float]) -> TriageSettings:
    return TriageSettings(
        duplicate_min_score=values["duplicate_min_score"],
        duplicate_likely_threshold=values["duplicate_likely_threshold"],
        duplicate_top_k=int(values["duplicate_top_k"]),
        cold_start_threshold=int(values["cold_start_threshold"]),
        exploration_rate=values["exploration_rate"],
        availability_bonus=values["availability_bonus"],
        duplicate_timeout_ms=int(values["duplicate_timeout_ms"]),
        severity_timeout_ms=int(values["severity_timeout_ms"]),
        assignment_timeout_ms=int(values["assignment_timeout_ms"]),
    )


def load_developers(db: Session, project_id: int) -> list[DeveloperInfo]:
    """Assignment candidates: active users with the Developer role in this project."""
    rows = db.execute(
        select(User, DeveloperProfile)
        .join(ProjectMember, ProjectMember.user_id == User.id)
        .outerjoin(DeveloperProfile, DeveloperProfile.user_id == User.id)
        .where(
            ProjectMember.project_id == project_id,
            ProjectMember.role == ProjectRole.DEVELOPER,
            User.is_active.is_(True),
        )
        .order_by(User.id)
    ).all()
    if not rows:
        return []
    ids = [user.id for user, _ in rows]
    workload = dict(
        db.execute(
            select(Bug.assignee_id, func.count())
            .where(Bug.assignee_id.in_(ids), Bug.status.in_(ACTIVE))
            .group_by(Bug.assignee_id)
        ).all()
    )
    resolved: dict[int, list[int]] = defaultdict(list)
    for developer_id, bug_id in db.execute(
        select(ResolutionHistory.developer_id, ResolutionHistory.bug_id)
        .where(ResolutionHistory.developer_id.in_(ids), ResolutionHistory.reopened.is_(False))
        .order_by(ResolutionHistory.resolved_at.desc())
    ).all():
        if len(resolved[developer_id]) < RESOLVED_PER_DEVELOPER:
            resolved[developer_id].append(bug_id)

    developers = []
    for user, profile in rows:
        words = (
            [*profile.skills, *profile.components, *profile.languages]
            if profile is not None
            else []
        )
        developers.append(
            DeveloperInfo(
                developer_id=user.id,
                name=user.full_name,
                resolved_count=profile.resolved_count if profile else len(resolved[user.id]),
                profile_text=" ".join(words),
                resolved_bug_ids=tuple(resolved[user.id]),
                availability=profile.availability.value if profile else "Available",
                workload=int(workload.get(user.id, 0)),
                max_workload=profile.max_workload if profile else 5,
                active=profile.active if profile else True,
            )
        )
    return developers


def _steps_dict(steps: dict[str, StepReport]) -> dict[str, dict[str, Any]]:
    return {
        name: {
            "status": report.status.value,
            "elapsed_ms": report.elapsed_ms,
            "detail": report.detail,
        }
        for name, report in steps.items()
    }


def _unavailable(steps: Sequence[str], notice: str) -> AiOutcome:
    reports = {
        name: StepReport(
            StepStatus.DEGRADED if name in steps else StepStatus.SKIPPED,
            0.0,
            notice if name in steps else None,
        )
        for name in ALL_STEPS_ORDER
    }
    if SEVERITY in steps:
        notice = f"{notice} {NOTICE_SEVERITY}"
    return AiOutcome(ai_status=AiStatus.DEGRADED, steps=_steps_dict(reports), notice=notice)


def _notice(result: TriageResult, steps: Sequence[str]) -> str | None:
    failed = [n for n, r in result.steps.items() if r.status == StepStatus.DEGRADED]
    if not failed:
        return None
    labels = {DUPLICATES: "duplicate check", SEVERITY: "severity", ASSIGNMENT: "recommendation"}
    text = "AI " + ", ".join(labels[n] for n in failed) + " unavailable for this report."
    if SEVERITY in failed:
        text += " " + NOTICE_SEVERITY
    return text


def _outcome(db: Session, result: TriageResult, steps: Sequence[str]) -> AiOutcome:
    found = {c.bug_id: c for c in result.duplicate_candidates}
    duplicates: list[dict[str, Any]] = []
    if found:
        bugs = {
            b.id: b
            for b in db.execute(
                select(Bug.id, Bug.title, Bug.status).where(Bug.id.in_(found))
            ).all()
        }
        for bug_id, candidate in found.items():
            if bug_id in bugs:
                duplicates.append(
                    {
                        "bug_id": bug_id,
                        "title": bugs[bug_id].title,
                        "status": bugs[bug_id].status.value,
                        "score": candidate.score,
                    }
                )
    severity = Severity(result.severity) if result.severity else None
    return AiOutcome(
        ai_status=AiStatus.OK if result.ok else AiStatus.DEGRADED,
        severity=severity,
        confidence=result.confidence,
        probabilities=result.probabilities,
        duplicates=duplicates,
        is_likely_duplicate=result.is_likely_duplicate,
        recommendations=[
            {
                "developer_id": r.developer_id,
                "name": r.name,
                "score": r.score,
                "reason": r.reason,
                "alpha": r.alpha,
                "history_score": r.history_score,
                "profile_score": r.profile_score,
                "explored": r.explored,
                "notes": list(r.notes),
            }
            for r in result.recommendations
        ],
        steps=_steps_dict(result.steps),
        total_ms=result.total_ms,
        notice=_notice(result, steps),
        vector=result.query_vector,
    )
