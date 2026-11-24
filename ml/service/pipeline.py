"""The triage pipeline: duplicates -> severity -> assignment over one shared TriageContext.

Every step runs in a worker thread with its own time budget. A step that raises, times out or
whose model is missing is recorded as `degraded`; the following steps still run with whatever
shared state is available (NFR-10). Step timings are logged for the latency report (NFR-02).

Steps compute their results without touching the context and the pipeline applies them, so a
step that finishes after its timeout can never change a result that was already returned.
"""

import logging
import random
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ml.assignment.cold_start import Candidate, Recommendation, recommend
from ml.duplicate.detector import DuplicateCandidate
from ml.service.context import (
    ALL_STEPS_ORDER,
    ASSIGNMENT,
    DUPLICATES,
    SEVERITY,
    StepReport,
    StepStatus,
    TriageContext,
    TriageResult,
)
from ml.service.index import BugIndex
from ml.service.models import TriageModels
from ml.severity.model import SeverityPrediction

logger = logging.getLogger("ml.triage")

ALL_STEPS = ALL_STEPS_ORDER
HISTORY_NEIGHBOURS = 3


class StepUnavailableError(RuntimeError):
    """The model a step needs is not loaded."""


@dataclass(frozen=True)
class DuplicateOutput:
    vector: NDArray[np.float32]
    candidates: list[DuplicateCandidate]


@dataclass(frozen=True)
class AssignmentOutput:
    recommendations: list[Recommendation]
    original_fixers: list[int]
    history_source: str
    vector: NDArray[np.float32] | None = None


@dataclass
class TriagePipeline:
    models: TriageModels
    index: BugIndex
    workers: int = 8
    rng: random.Random = field(default_factory=random.Random)
    _executor: ThreadPoolExecutor = field(init=False)

    def __post_init__(self) -> None:
        self._executor = ThreadPoolExecutor(self.workers, thread_name_prefix="triage")

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    # ------------------------------------------------------------------ public API
    def run(self, ctx: TriageContext, steps: Iterable[str] = ALL_STEPS) -> TriageResult:
        wanted = set(steps)
        started = time.perf_counter()
        budget = ctx.settings
        if DUPLICATES in wanted:
            self._run_step(
                ctx, DUPLICATES, self.find_duplicates, budget.duplicate_timeout_ms, self._apply_dup
            )
        if SEVERITY in wanted:
            self._run_step(
                ctx, SEVERITY, self.classify, budget.severity_timeout_ms, self._apply_severity
            )
        if ASSIGNMENT in wanted:
            self._run_step(
                ctx, ASSIGNMENT, self.assign, budget.assignment_timeout_ms, self._apply_assign
            )
        for name in ALL_STEPS:
            ctx.steps.setdefault(name, StepReport(StepStatus.SKIPPED, 0.0))
        total_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "triage project=%s total_ms=%.1f %s",
            ctx.project_id,
            total_ms,
            " ".join(f"{n}={r.status.value}:{r.elapsed_ms:.1f}ms" for n, r in ctx.steps.items()),
        )
        return TriageResult.from_context(ctx, total_ms)

    def _run_step(
        self,
        ctx: TriageContext,
        name: str,
        compute: Callable[[TriageContext], Any],
        timeout_ms: int,
        apply: Callable[[TriageContext, Any], str | None],
    ) -> None:
        started = time.perf_counter()
        future: Future[Any] = self._executor.submit(compute, ctx)
        try:
            output = future.result(timeout=timeout_ms / 1000)
            detail = apply(ctx, output)
            report = StepReport(StepStatus.OK, _ms(started), detail)
        except FutureTimeout:
            future.cancel()
            report = StepReport(
                StepStatus.DEGRADED, _ms(started), f"timed out after {timeout_ms} ms"
            )
        except StepUnavailableError as exc:
            report = StepReport(StepStatus.DEGRADED, _ms(started), str(exc))
        except Exception as exc:
            logger.exception("triage step %s failed", name)
            report = StepReport(StepStatus.DEGRADED, _ms(started), f"failed: {type(exc).__name__}")
        ctx.steps[name] = report
        logger.info(
            "triage step=%s status=%s elapsed_ms=%.1f", name, report.status.value, report.elapsed_ms
        )

    # ------------------------------------------------------------------ step 1: duplicates
    def embed(self, text: str) -> NDArray[np.float32]:
        if self.models.encoder is None:
            raise StepUnavailableError(
                self.models.errors.get("embedding", "embedding model not loaded")
            )
        vector: NDArray[np.float32] = self.models.encoder.encode([text])[0]
        return vector

    def find_duplicates(self, ctx: TriageContext) -> DuplicateOutput:
        vector = self.embed(ctx.embed_text)
        candidates = self.index.search(
            ctx.project_id,
            ctx.text,
            vector,
            top_k=ctx.settings.duplicate_top_k,
            min_score=ctx.settings.duplicate_min_score,
            exclude=set(ctx.exclude_bug_ids),
        )
        return DuplicateOutput(vector, candidates)

    @staticmethod
    def _apply_dup(ctx: TriageContext, output: DuplicateOutput) -> str | None:
        ctx.query_vector = output.vector
        ctx.duplicate_candidates = output.candidates
        ctx.is_likely_duplicate = bool(ctx.likely_originals)
        return None

    # ------------------------------------------------------------------ step 2: severity
    def classify(self, ctx: TriageContext) -> SeverityPrediction:
        if self.models.severity is None:
            raise StepUnavailableError(
                self.models.errors.get("severity", "severity model not loaded")
            )
        return self.models.severity.predict([ctx.text])[0]

    @staticmethod
    def _apply_severity(ctx: TriageContext, output: SeverityPrediction) -> str | None:
        ctx.severity = output.label
        ctx.confidence = round(output.confidence, 4)
        ctx.probabilities = dict(output.probabilities)
        return None

    # ------------------------------------------------------------------ step 3: assignment
    def history_scores(
        self, ctx: TriageContext, vector: NDArray[np.float32] | None
    ) -> tuple[dict[int, float], str]:
        """History evidence per developer, rescaled to [0, 1] within its source.

        1. CNN-LSTM trained on this system's resolutions, for the developers it knows; its
           probabilities are rescaled so the best of them is 1.
        2. Otherwise similarity to the developer's own resolved reports: mean cosine of the
           3 most similar resolved reports (k-NN over the duplicate-index embeddings). This is
           already an absolute 0-1 similarity, comparable with the profile cosine, so it is
           not rescaled: a weak history match must not outrank a strong skill match.
        Developers with neither get no history score, so alpha = 0 for them (cold start).
        """
        scores: dict[int, float] = {}
        sources: list[str] = []
        model = self.models.history
        if model is not None:
            known = {label: i for i, label in enumerate(model.developers)}
            ids = [d.developer_id for d in ctx.developers if str(d.developer_id) in known]
            if ids:
                row = model.probabilities([ctx.assignment_text])[0]
                raw = {d: float(row[known[str(d)]]) for d in ids}
                scores.update(_rescale(raw))
                sources.append("cnn-lstm")
        if vector is not None:
            raw = {}
            for developer in ctx.developers:
                if developer.developer_id in scores or not developer.resolved_bug_ids:
                    continue
                resolved = self.index.vectors(developer.resolved_bug_ids)
                if len(resolved):
                    similarity = np.sort(resolved @ vector)[::-1][:HISTORY_NEIGHBOURS]
                    raw[developer.developer_id] = max(0.0, float(similarity.mean()))
            if raw:
                scores.update({k: min(1.0, v) for k, v in raw.items()})
                sources.append("resolved-report similarity")
        return scores, " + ".join(sources) or "none"

    def assign(self, ctx: TriageContext) -> AssignmentOutput:
        vector = ctx.query_vector
        if vector is None and self.models.encoder is not None:
            vector = self.embed(ctx.embed_text)
        history, source = self.history_scores(ctx, vector)
        originals = set(ctx.likely_originals) if ctx.is_likely_duplicate else set()
        fixers = [d.developer_id for d in ctx.developers if originals & set(d.resolved_bug_ids)]
        candidates = [
            Candidate(
                developer_id=d.developer_id,
                name=d.name,
                resolved_count=d.resolved_count,
                profile_text=d.profile_text,
                history_score=history.get(d.developer_id),
                availability=d.availability,
                workload=d.workload,
                max_workload=d.max_workload,
                active=d.active,
            )
            for d in ctx.developers
        ]
        settings = ctx.settings
        recommendations = recommend(
            " ".join([*ctx.components, ctx.text]),  # profile matching uses plain words
            candidates,
            threshold=settings.cold_start_threshold,
            epsilon=settings.exploration_rate,
            availability_bonus=settings.availability_bonus,
            top_k=settings.recommendation_top_k,
            severity=ctx.severity,
            original_fixers=fixers,
            rng=self.rng,
            normalize_history=False,  # each source is already on a 0-1 scale (see above)
        )
        return AssignmentOutput(recommendations, fixers, source, vector)

    @staticmethod
    def _apply_assign(ctx: TriageContext, output: AssignmentOutput) -> str | None:
        ctx.recommendations = output.recommendations
        ctx.original_fixers = output.original_fixers
        if ctx.query_vector is None and output.vector is not None:
            ctx.query_vector = output.vector
        return f"history: {output.history_source}"


def _rescale(raw: dict[int, float]) -> dict[int, float]:
    best = max(raw.values(), default=0.0)
    if best <= 0:
        return dict.fromkeys(raw, 0.0)
    return {k: v / best for k, v in raw.items()}


def _ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
