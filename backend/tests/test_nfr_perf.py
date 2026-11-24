"""Performance requirements with the REAL models (marker `perf`, run with `make test-perf`).

* NFR-02 in-process: the trained models and a duplicate index of 50,000 real Eclipse reports,
  timed per pipeline step (no HTTP). Skipped when the artifacts or datasets are missing.
* NFR-01/02/03 over HTTP: against the benchmark server (`make bench-up`, BENCH_URL), using
  the same code as `scripts/loadtest.py` with shorter runs. Skipped when BENCH_URL is unset.

The full-length runs that produce docs/results/*.json are `make bench`.
"""

import asyncio
import json
import os
import time
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pytest

from ml.common.paths import ARTIFACTS, PROCESSED, RESULTS
from ml.common.text import report_text
from ml.service.context import (
    ASSIGNMENT,
    DUPLICATES,
    SEVERITY,
    DeveloperInfo,
    StepStatus,
    TriageContext,
)
from ml.service.index import BugIndex
from ml.service.models import load_models
from ml.service.pipeline import TriagePipeline

pytestmark = pytest.mark.perf

BENCH_URL = os.environ.get("BENCH_URL", "")
needs_artifacts = pytest.mark.skipif(
    not (ARTIFACTS / "severity" / "eclipse.joblib").exists()
    or not (PROCESSED / "eclipse.parquet").exists(),
    reason="needs trained models and processed data (make data train eval)",
)
needs_server = pytest.mark.skipif(not BENCH_URL, reason="set BENCH_URL (make bench-up)")


def p95(values: list[float]) -> float:
    return float(np.percentile(np.asarray(values), 95))


@needs_artifacts
def test_nfr02_pipeline_latency_with_real_models_and_50k_index() -> None:
    from scripts.bench_data import load_reports

    reports, holdout, vectors = load_reports(50_000, 100)
    models = load_models(ARTIFACTS, threads=int(os.environ.get("OMP_NUM_THREADS", "2")))
    assert models.encoder is not None and models.severity is not None, models.errors
    index = BugIndex(models.encoder.encode, dimension=models.encoder.dimension)
    started = time.perf_counter()
    texts = [
        report_text(t, d) for t, d in zip(reports["title"], reports["description"], strict=True)
    ]
    index.add_many(1, list(range(1, len(reports) + 1)), texts, vectors)
    build_s = time.perf_counter() - started

    fixers = reports["fixer"].dropna().value_counts().head(10).index
    developers = [
        DeveloperInfo(
            developer_id=i + 1,
            name=f"dev{i + 1}",
            resolved_count=int((reports["fixer"] == f).sum()),
            profile_text=" ".join(reports.loc[reports["fixer"] == f, "component"].astype(str)[:50]),
            resolved_bug_ids=tuple(int(x) + 1 for x in np.flatnonzero(reports["fixer"] == f)[-50:]),
        )
        for i, f in enumerate(fixers)
    ] + [DeveloperInfo(99, "newcomer", 0, "ui swt accessibility")]
    pipeline = TriagePipeline(models, index)

    steps: dict[str, list[float]] = {DUPLICATES: [], SEVERITY: [], ASSIGNMENT: []}
    totals, combined = [], []
    for i, row in enumerate(holdout.itertuples()):
        result = pipeline.run(
            TriageContext(
                title=str(row.title),
                description=str(row.description),
                project_id=1,
                components=[str(row.component)],
                developers=developers,
            )
        )
        assert {s.status for s in result.steps.values()} == {StepStatus.OK}, result.steps
        if i < 5:
            continue  # warm-up
        for name in steps:
            steps[name].append(result.steps[name].elapsed_ms)
        combined.append(result.steps[DUPLICATES].elapsed_ms + result.steps[SEVERITY].elapsed_ms)
        totals.append(result.total_ms)
    pipeline.shutdown()

    summary = {
        name: {"p50_ms": round(float(np.median(v)), 1), "p95_ms": round(p95(v), 1)}
        for name, v in {**steps, "duplicates_plus_severity": combined, "total": totals}.items()
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "pipeline_latency_inprocess.json").write_text(
        json.dumps(
            {
                "provenance": {
                    "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    "method": "In-process TriagePipeline with the trained models; duplicate "
                    "index of the 50,000 most recent Eclipse Platform reports; 95 held-out "
                    "later reports (5 warm-up runs not counted); 11 candidate developers; "
                    "per-step wall time including thread hand-off.",
                    "threads": os.environ.get("OMP_NUM_THREADS", "2"),
                },
                "index_reports": len(reports),
                "index_build_seconds": round(build_s, 1),
                "model_load_seconds": models.load_seconds,
                "queries": len(totals),
                "steps": summary,
                "pass": {
                    "duplicates_plus_severity_p95_le_1500ms": p95(combined) <= 1500,
                    "assignment_p95_le_3000ms": p95(steps[ASSIGNMENT]) <= 3000,
                },
            },
            indent=2,
        )
    )
    assert p95(combined) <= 1500  # NFR-02
    assert p95(steps[ASSIGNMENT]) <= 3000  # NFR-02


@needs_server
def test_nfr02_over_http() -> None:
    from scripts.loadtest import latency, wait_ready

    assert asyncio.run(wait_ready(BENCH_URL))["state"] == "ready"
    result: dict[str, Any] = asyncio.run(latency(BENCH_URL, reports=50, save=False))
    assert all(result["pass"].values()), result["pass"]


@needs_server
def test_nfr01_100_concurrent_users_browse() -> None:
    from scripts.loadtest import browse

    result: dict[str, Any] = asyncio.run(browse(BENCH_URL, users=100, duration=40, save=False))
    assert all(result["pass"].values()), (result["pass"], result["under_load"])


@needs_server
def test_nfr03_50_concurrent_submissions() -> None:
    from scripts.loadtest import submissions

    result: dict[str, Any] = asyncio.run(
        submissions(BENCH_URL, users=50, duration=40, baseline=40, save=False)
    )
    assert result["load"]["errors"] == 0
    assert result["pass"], result["degradation"]
