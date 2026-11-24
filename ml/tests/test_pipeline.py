"""Shared-state triage pipeline: step order, shared state, timeouts and degraded steps.

All models here are SYNTHETIC test doubles (keyword rules and bag-of-words vectors); they test
the pipeline's behaviour, not model quality.
"""

import random
import time
from typing import ClassVar

import numpy as np
from numpy.typing import NDArray

from ml.service.context import (
    ASSIGNMENT,
    DUPLICATES,
    SEVERITY,
    DeveloperInfo,
    StepStatus,
    TriageContext,
    TriageSettings,
)
from ml.service.index import BugIndex
from ml.service.models import TriageModels
from ml.service.pipeline import TriagePipeline
from ml.severity.model import SeverityPrediction

VOCAB = ["crash", "save", "editor", "theme", "login", "network", "payment", "card", "declined"]


class FakeEncoder:
    dimension = len(VOCAB)

    def encode(self, texts: list[str]) -> NDArray[np.float32]:
        vectors = np.array([[t.lower().count(w) for w in VOCAB] for t in texts], dtype=np.float32)
        norms = np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-9)
        result: NDArray[np.float32] = (vectors / norms).astype(np.float32)
        return result


class FakeSeverity:
    def __init__(self, delay: float = 0.0, fail: bool = False) -> None:
        self.delay = delay
        self.fail = fail

    def predict(self, texts: list[str]) -> list[SeverityPrediction]:
        time.sleep(self.delay)
        if self.fail:
            raise RuntimeError("model exploded")
        label = "Critical" if "crash" in texts[0].lower() else "Medium"
        return [SeverityPrediction(label, 0.9, {label: 0.9})]


class FakeHistory:
    developers: ClassVar[list[str]] = ["1"]

    def probabilities(self, texts: list[str]) -> NDArray[np.float32]:
        return np.array([[0.7]], dtype=np.float32)


def build_index() -> BugIndex:
    index = BugIndex(FakeEncoder().encode, dimension=len(VOCAB))
    index.add_many(
        1,
        [10, 11, 12],
        [
            "Editor crash on save. The editor crashes when I save a file",
            "Login fails on network change",
            "Payment card declined twice",
        ],
    )
    filler = ["Printing margins", "Font blurry", "Help typo", "Shortcut missing", "Icon offset"]
    index.add_many(1, list(range(100, 105)), filler)
    index.add_many(2, [20], ["Editor crash on save in another project"])
    return index


DEVELOPERS = (
    # 1: resolved the original (bug 10), but is unavailable
    DeveloperInfo(1, "Ann", 12, "editor save files", (10,), availability="Unavailable"),
    # 2: resolved the original bug 10, available
    DeveloperInfo(2, "Ben", 4, "editor", (10, 11)),
    # 3: unrelated skills, at max workload
    DeveloperInfo(3, "Cat", 20, "payments card", (12,), workload=5, max_workload=5),
    # 4: brand-new developer whose skills match
    DeveloperInfo(4, "Dan", 0, "editor crash save"),
)


def context(**overrides: object) -> TriageContext:
    values: dict[str, object] = {
        "title": "Editor crashes when saving",
        "description": "The editor crash happens on every save of a large file",
        "project_id": 1,
        "components": ["editor"],
        "developers": DEVELOPERS,
        "settings": TriageSettings(duplicate_min_score=0.3, duplicate_likely_threshold=0.6),
    }
    values.update(overrides)
    return TriageContext(**values)  # type: ignore[arg-type]


def pipeline(**models: object) -> TriagePipeline:
    values: dict[str, object] = {"encoder": FakeEncoder(), "severity": FakeSeverity()}
    values.update(models)
    return TriagePipeline(TriageModels(**values), build_index(), rng=random.Random(1))  # type: ignore[arg-type]  # noqa: S311


def test_full_run_shares_state_between_steps() -> None:
    result = pipeline().run(context())

    assert result.ok and result.total_ms > 0
    assert {r.status for r in result.steps.values()} == {StepStatus.OK}
    # duplicates: same project only, the original first and marked as likely
    assert result.duplicate_candidates[0].bug_id == 10
    assert 20 not in {c.bug_id for c in result.duplicate_candidates}
    assert result.is_likely_duplicate
    # severity
    assert result.severity == "Critical" and result.confidence == 0.9
    # assignment reads both: Critical drops Ann (unavailable) and Cat (full) ...
    ids = [r.developer_id for r in result.recommendations]
    assert 1 not in ids and 3 not in ids
    # ... and the developer who fixed the original gets the duplicate boost
    ben = next(r for r in result.recommendations if r.developer_id == 2)
    assert ben.notes == ("fixed the original of this likely duplicate",)
    assert ids[0] == 2
    # the new developer is still recommended, with the cold-start reason
    dan = next(r for r in result.recommendations if r.developer_id == 4)
    assert dan.reason == "new developer (cold start)" and dan.alpha == 0
    assert result.query_vector is not None
    assert "resolved-report similarity" in (result.steps[ASSIGNMENT].detail or "")


def test_not_critical_keeps_unavailable_developers_in_the_pool() -> None:
    result = pipeline().run(context(title="Theme colours wrong", description="Theme is off a lot"))
    assert result.severity == "Medium"
    assert len(result.recommendations) == 3


def test_slow_step_times_out_and_the_rest_still_runs() -> None:
    settings = TriageSettings(severity_timeout_ms=100, duplicate_min_score=0.3)
    started = time.perf_counter()
    result = pipeline(severity=FakeSeverity(delay=0.5)).run(context(settings=settings))

    assert time.perf_counter() - started < 0.45  # did not wait for the slow model
    assert result.steps[SEVERITY].status == StepStatus.DEGRADED
    assert "timed out" in (result.steps[SEVERITY].detail or "")
    assert result.severity is None
    assert result.steps[DUPLICATES].status == StepStatus.OK
    assert result.steps[ASSIGNMENT].status == StepStatus.OK
    assert result.recommendations  # without a severity nobody is filtered out
    assert not result.ok
    time.sleep(0.5)  # the late answer must not leak into the returned result
    assert result.severity is None


def test_failing_model_is_degraded_not_raised() -> None:
    result = pipeline(severity=FakeSeverity(fail=True)).run(context())
    assert result.steps[SEVERITY].status == StepStatus.DEGRADED
    assert result.steps[SEVERITY].detail == "failed: RuntimeError"
    assert result.steps[ASSIGNMENT].status == StepStatus.OK


def test_missing_models_degrade_only_their_steps() -> None:
    models = TriageModels(encoder=None, severity=FakeSeverity(), errors={"embedding": "gone"})
    result = TriagePipeline(models, build_index()).run(context())
    assert result.steps[DUPLICATES].status == StepStatus.DEGRADED
    assert result.steps[DUPLICATES].detail == "gone"
    assert result.duplicate_candidates == [] and not result.is_likely_duplicate
    assert result.severity == "Critical"
    # without embeddings the recommender falls back to profile matching only
    assert result.steps[ASSIGNMENT].status == StepStatus.OK
    assert all(r.alpha == 0 for r in result.recommendations)


def test_requested_steps_only() -> None:
    result = pipeline().run(context(), steps=[DUPLICATES])
    assert result.steps[DUPLICATES].status == StepStatus.OK
    assert result.steps[SEVERITY].status == StepStatus.SKIPPED
    assert result.steps[ASSIGNMENT].status == StepStatus.SKIPPED
    assert result.severity is None and result.recommendations == []
    assert result.ok


def test_live_cnn_lstm_is_used_for_developers_it_knows() -> None:
    result = pipeline(history=FakeHistory()).run(
        context(title="Theme colours wrong", description="Theme is off a lot")
    )
    assert "cnn-lstm" in (result.steps[ASSIGNMENT].detail or "")
    ann = next(r for r in result.recommendations if r.developer_id == 1)
    assert ann.history_score == 1.0  # the only developer the model knows -> best of its source


def test_index_incremental_add_and_exclude() -> None:
    p = pipeline()
    p.index.add(1, 30, "Network login timeout when the network drops", None)
    assert p.index.size(1) == 9 and p.index.contains(30)
    result = p.run(
        context(
            title="Login network",
            description="login network fails",
            exclude_bug_ids=frozenset({11}),
        ),
        steps=[DUPLICATES],
    )
    ids = [c.bug_id for c in result.duplicate_candidates]
    assert 30 in ids and 11 not in ids
    p.index.drop_project(1)
    assert p.index.size(1) == 0 and not p.index.contains(30) and p.index.contains(20)
