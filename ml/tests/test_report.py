"""RESULTS.md must be built only from result files; missing files become NOT RUN rows."""

import json
from pathlib import Path

import pytest

from ml import report


def test_missing_results_are_reported_as_not_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report, "RESULTS", tmp_path)
    path = report.main()
    text = path.read_text()
    assert text.count("NOT RUN") >= 5
    assert "PASS |" not in text and "FAIL |" not in text


def test_pass_fail_comes_from_the_numbers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report, "RESULTS", tmp_path)
    reassign = {
        "model_mean": 5.0,
        "random_mean_over_5_seeds": 50.0,
        "reduction_vs_random": 0.9,
        "component_heuristic_mean": 6.0,
        "reduction_vs_component_heuristic": 0.17,
        "observed_bugzilla_assignee_changes_mean": 1.2,
    }
    payload = {
        "provenance": {"generated_at": "2026-01-01T00:00:00+00:00"},
        "candidate_developers": 3,
        "train_size": 10,
        "test_size_covered": 5,
        "test_coverage": 0.5,
        "reassignments": reassign,
        "accuracy": {"top1": 0.1, "top3": 0.2, "top5": 0.3},
        "latency_ms_single_report": {"p95": 4000.0},
    }
    (tmp_path / "assignment_eclipse.json").write_text(json.dumps(payload))
    text = report.main().read_text()
    assert "| Reassignment reduction vs random - eclipse | >= 20% | **90.0%** | PASS |" in text
    assert "| Assignment inference p95 - eclipse | < 3 s | **4000 ms** | FAIL |" in text
