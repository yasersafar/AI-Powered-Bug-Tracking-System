"""Build docs/results/RESULTS.md from the JSON files written by the evaluate scripts.

    python -m ml.report

Every number in the table is read from a results file produced by a script that was run;
a missing file is reported as NOT RUN. The hand-written analysis of missed targets lives in
docs/results/analysis.md and is appended verbatim.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ml.common.paths import RESULTS


@dataclass
class Row:
    metric: str
    target: str
    achieved: str
    passed: bool | None  # None = informational / not run
    method: str
    date: str
    size: str


def _load(name: str) -> dict[str, Any] | None:
    path = RESULTS / name
    return json.loads(path.read_text()) if path.exists() else None


def _date(result: dict[str, Any]) -> str:
    return str(result["provenance"]["generated_at"])[:10]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _not_run(metric: str, target: str, file: str) -> Row:
    reason = NOT_RUN_REASONS.get(file, f"`{file}` missing - run `make eval`")
    return Row(metric, target, "NOT RUN", None, reason, "-", "-")


NOT_RUN_REASONS = {
    "severity_mozilla.json": "Not run: ~45 min of full CPU load (10-fold CV on ~250k reports) on a "
    "laptop that was overheating; Eclipse is the primary severity dataset. Command: "
    "`python -m ml.severity.train --ecosystem mozilla && python -m ml.severity.evaluate "
    "--ecosystem mozilla`",
}


def severity_rows() -> list[Row]:
    rows = [_not_run("Severity accuracy (mozilla)", ">= 85%", "severity_mozilla.json")]
    if _load("severity_mozilla.json") is not None:
        rows = []  # if someone runs it, extend this function to report it
    result = _load("severity_eclipse.json")
    if result is None:
        return [_not_run("Severity accuracy", ">= 85%", "severity_eclipse.json"), *rows]
    ensemble = result["models"]["soft_voting_ensemble"]
    split = result["split"]
    size = f"train {split['train_size']:,} / test {split['test_size']:,} (Eclipse)"
    method = "Time-based 80/20 split; TF-IDF + soft-voting ensemble; 10-fold CV on train only"
    baseline = next(v for k, v in result["models"].items() if k.startswith("baseline_majority"))
    return [
        Row(
            "Severity accuracy",
            ">= 85%",
            _pct(ensemble["accuracy"]),
            ensemble["accuracy"] >= 0.85,
            method,
            _date(result),
            size,
        ),
        Row(
            "Severity macro-F1",
            "(info)",
            f"{ensemble['macro_f1']:.3f}",
            None,
            "Same test set; majority-class baseline accuracy "
            f"{_pct(baseline['accuracy'])}, macro-F1 {baseline['macro_f1']:.3f}",
            _date(result),
            size,
        ),
        Row(
            "Severity inference p95 (one report)",
            "(part of <= 1.5 s)",
            f"{result['latency_ms_single_report']['p95']:.0f} ms",
            None,
            "Model only, 200 test reports, CPU",
            _date(result),
            size,
        ),
        *rows,
    ]


def duplicate_rows() -> list[Row]:
    rows: list[Row] = []
    for dataset in ("eclipse_platform", "eclipse_jdt"):
        result = _load(f"duplicates_{dataset}.json")
        if result is None:
            rows.append(
                _not_run(f"Duplicate Recall@5 ({dataset})", "> 80%", f"duplicates_{dataset}.json")
            )
            continue
        weight = result["pipeline"]["chosen_w"]
        realistic = result["test_realistic_pool_all_earlier_reports"]
        comparable = result["test_benchmark_comparable_pool_test_period_only"]
        best = realistic[f"w={weight}"]
        size = f"{result['reports']:,} reports, {realistic['queries']:,} test queries"
        rows += [
            Row(
                f"Duplicate Recall@5 - {dataset}, whole history",
                "> 80%",
                _pct(best["recall@5"]),
                best["recall@5"] > 0.8,
                f"BM25 top-50 -> MiniLM re-rank (w={weight}); each query searches all earlier "
                "reports",
                _date(result),
                size,
            ),
            Row(
                f"Duplicate Recall@5 - {dataset}, test-period pool",
                "> 80%",
                _pct(comparable[f"w={weight}"]["recall@5"]),
                comparable[f"w={weight}"]["recall@5"] > 0.8,
                "Pool limited to the test period (closer to Meng et al. 2024)",
                _date(result),
                f"{comparable['queries']:,} queries",
            ),
            Row(
                f"Duplicate MRR / Recall@1 / Recall@10 - {dataset}",
                "(info)",
                f"{best['mrr']:.3f} / {_pct(best['recall@1'])} / {_pct(best['recall@10'])}",
                None,
                "Whole-history setting",
                _date(result),
                size,
            ),
            Row(
                f"Duplicate search p95 - {dataset}",
                "< 1.5 s",
                f"{result['latency_live_search']['p95_ms']:.0f} ms",
                result["latency_live_search"]["p95_ms"] < 1500,
                f"Embed query + BM25 + re-rank over {result['latency_live_search']['index_size']:,}"
                " indexed reports, CPU",
                _date(result),
                size,
            ),
        ]
    return rows


def assignment_rows() -> list[Row]:
    rows: list[Row] = []
    for ecosystem in ("eclipse", "mozilla"):
        result = _load(f"assignment_{ecosystem}.json")
        if result is None:
            rows.append(
                _not_run(
                    f"Reassignment reduction ({ecosystem})",
                    ">= 20%",
                    f"assignment_{ecosystem}.json",
                )
            )
            continue
        r = result["reassignments"]
        acc = result["accuracy"]
        size = (
            f"{result['candidate_developers']} developers; train {result['train_size']:,} / "
            f"test {result['test_size_covered']:,} ({_pct(result['test_coverage'])} covered)"
        )
        rows += [
            Row(
                f"Reassignment reduction vs random - {ecosystem}",
                ">= 20%",
                _pct(r["reduction_vs_random"]),
                r["reduction_vs_random"] >= 0.2,
                f"Simulated tossing: model {r['model_mean']:.2f} vs random "
                f"{r['random_mean_over_5_seeds']:.2f} reassignments/bug (5 seeds)",
                _date(result),
                size,
            ),
            Row(
                f"Reassignment reduction vs component heuristic - {ecosystem}",
                "(info)",
                _pct(r["reduction_vs_component_heuristic"]),
                None,
                f"Heuristic {r['component_heuristic_mean']:.2f}; observed in Bugzilla "
                f"{r['observed_bugzilla_assignee_changes_mean']:.2f}",
                _date(result),
                size,
            ),
            Row(
                f"Assignment Top-1 / Top-3 / Top-5 - {ecosystem}",
                "(info)",
                f"{_pct(acc['top1'])} / {_pct(acc['top3'])} / {_pct(acc['top5'])}",
                None,
                "Time-based 80/20 split, CNN-LSTM",
                _date(result),
                size,
            ),
            Row(
                f"Assignment inference p95 - {ecosystem}",
                "< 3 s",
                f"{result['latency_ms_single_report']['p95']:.0f} ms",
                result["latency_ms_single_report"]["p95"] < 3000,
                "Model only, one report, CPU",
                _date(result),
                size,
            ),
        ]
    return rows


def _p95(summary: dict[str, Any]) -> str:
    return f"{summary['p95_ms']:.0f} ms"


def integration_rows() -> list[Row]:
    """Stage 5: the models inside the running backend, measured over HTTP (scripts/loadtest)."""
    rows: list[Row] = []
    latency = _load("api_latency.json")
    if latency is None:
        rows.append(_not_run("API triage latency (NFR-02)", "<= 1.5 s / 3 s", "api_latency.json"))
    else:
        server = latency["provenance"]["server"]
        size = f"{server['ai']['indexed_reports']:,} indexed reports; {latency['reports']} queries"
        both, assign = latency["duplicates_plus_severity"], latency["endpoints"]["ai_assign"]
        triage = latency["endpoints"]["ai_triage"]
        rows += [
            Row(
                "NFR-02 duplicates + severity p95 (HTTP)",
                "<= 1.5 s",
                _p95(both),
                both["p95_ms"] <= 1500,
                "POST /ai/duplicates + /ai/severity per held-out report, one user, client side",
                _date(latency),
                size,
            ),
            Row(
                "NFR-02 assignment p95 (HTTP)",
                "<= 3 s",
                _p95(assign),
                assign["p95_ms"] <= 3000,
                "POST /ai/assign, one user, client side",
                _date(latency),
                size,
            ),
            Row(
                "Full triage p95 (HTTP)",
                "(info)",
                _p95(triage),
                None,
                "POST /ai/triage: all three steps over one shared context",
                _date(latency),
                size,
            ),
        ]
    inprocess = _load("pipeline_latency_inprocess.json")
    if inprocess is not None:
        steps = inprocess["steps"]
        rows.append(
            Row(
                "Pipeline steps p95 in-process (dup / sev / assign)",
                "(info)",
                f"{steps['duplicates']['p95_ms']:.0f} / {steps['severity']['p95_ms']:.0f} / "
                f"{steps['assignment']['p95_ms']:.0f} ms",
                None,
                "TriagePipeline with the trained models, no HTTP (tests/test_nfr_perf.py)",
                _date(inprocess),
                f"{inprocess['index_reports']:,} indexed reports",
            )
        )
    browse = _load("load_browse.json")
    if browse is None:
        rows.append(_not_run("NFR-01 list/search p95, 100 users", "<= 2 s", "load_browse.json"))
    else:
        under = browse["under_load"]
        worst = max(under, key=lambda k: under[k]["p95_ms"])
        errors = sum(v["errors"] for v in under.values())
        bugs = browse["provenance"]["server"]["bugs_in_database"]
        size = f"{bugs:,} bugs; {browse['requests']:,} requests"
        rows += [
            Row(
                "NFR-01 worst endpoint p95, 100 concurrent users",
                "<= 2 s",
                f"{under[worst]['p95_ms']:.0f} ms ({worst}), {errors} errors",
                browse["pass"]["nfr01_all_endpoints_p95_within_2s"],
                "List, keyword search, filtered search, detail, dashboard; think time 1-3 s",
                _date(browse),
                size,
            ),
            Row(
                "FR-07 search p95 on 50k bugs (alone / under load)",
                "<= 2 s",
                f"{max(v['p95_ms'] for k, v in browse['search_alone_fr07'].items()):.0f} / "
                f"{max(under[k]['p95_ms'] for k in ('keyword_search', 'filtered_search')):.0f} ms",
                browse["pass"]["fr07_search_p95_within_2s_alone"]
                and browse["pass"]["fr07_search_p95_within_2s_under_load"],
                "tsvector + GIN keyword search (relevance) and status/severity/date filters",
                _date(browse),
                size,
            ),
        ]
    submit = _load("load_submissions.json")
    if submit is None:
        rows.append(_not_run("NFR-03 latency degradation", "< 10%", "load_submissions.json"))
    else:
        base, load = submit["baseline_single_user"], submit["load"]
        burst = submit["burst_all_users_at_once_info_only"]
        size = f"{load['count']} submissions in {load['duration_s']:.0f} s, {load['errors']} errors"
        rows += [
            Row(
                "NFR-03 p95 latency degradation, 50 concurrent users",
                "< 10%",
                f"+{submit['degradation']['p95'] * 100:.1f}% (p95 {base['p95_ms']:.0f} -> "
                f"{load['p95_ms']:.0f} ms)",
                submit["pass"],
                "POST /bugs with full triage; 50 users, think time 2-8 s, vs 1 user",
                _date(submit),
                size,
            ),
            Row(
                "NFR-03 median degradation",
                "(info)",
                f"+{submit['degradation']['p50'] * 100:.1f}% (p50 {base['p50_ms']:.0f} -> "
                f"{load['p50_ms']:.0f} ms)",
                None,
                "Same run",
                _date(submit),
                size,
            ),
            Row(
                "Burst: 50 submissions at the same instant",
                "(info)",
                f"p95 {burst['p95_ms'] / 1000:.1f} s, {burst['errors']} errors, "
                f"{burst['ai_degraded']} degraded",
                None,
                "All saved; steps over their time budget are marked degraded (NFR-10)",
                _date(submit),
                "50 submissions",
            ),
        ]
    live = _load("assignment_live_bench.json")
    if live is not None:
        rows.append(
            Row(
                "Live CNN-LSTM top-1 / top-3 (benchmark DB)",
                "(info)",
                f"{_pct(live['test_top1'])} / {_pct(live['test_top3'])} "
                f"(majority {_pct(live['majority_class_top1'])})",
                None,
                "Trained on the system's resolution history (scripts/train_assignment.py); "
                "newest 20% by resolution date as test",
                str(live["generated_at"])[:10],
                f"{live['developers']} developers, "
                f"{sum(live['resolutions'].values()):,} resolutions",
            )
        )
    return rows


def render(rows: list[Row]) -> str:
    def status(value: bool | None) -> str:
        return {True: "PASS", False: "FAIL", None: "-"}[value]

    lines = [
        "# Evaluation results",
        "",
        "Generated by `python -m ml.report` from the JSON files in this folder. Every number",
        "comes from a script that was run (`make eval` for the models, `make bench` and",
        "`make test-perf` for the running system); nothing is typed in by hand.",
        "",
        "| Metric | Target | Achieved | Pass/Fail | How measured | Date | Dataset size |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.metric} | {r.target} | **{r.achieved}** | {status(r.passed)} | {r.method} | "
        f"{r.date} | {r.size} |"
        for r in rows
    ]
    lines += [
        "",
        "## Files",
        "",
        "| Task | Results | Figures |",
        "|---|---|---|",
        "| Severity | `severity_eclipse.json`, `severity_eclipse_cv.json`, "
        "`severity_eclipse_models.csv` | `severity_eclipse_confusion.png` |",
        "| Duplicates | `duplicates_eclipse_platform.json`, `duplicates_eclipse_jdt.json` | "
        "`duplicates_*_recall5.png` |",
        "| Assignment | `assignment_eclipse.json`, `assignment_mozilla.json` | "
        "`assignment_*_reassignments.png` |",
        "| Live CNN-LSTM | `assignment_live_bench.json` | - |",
        "| API latency (NFR-02) | `api_latency.json`, `pipeline_latency_inprocess.json` | - |",
        "| Load (NFR-01, NFR-03, FR-07) | `load_browse.json`, `load_submissions.json`, "
        "`load_submissions_before_fix.json`, `load_submissions_1worker.json` | - |",
        "",
    ]
    analysis = RESULTS / "analysis.md"
    if analysis.exists():
        lines += ["", analysis.read_text().strip(), ""]
    return "\n".join(lines)


def main() -> Path:
    rows = severity_rows() + duplicate_rows() + assignment_rows() + integration_rows()
    path = RESULTS / "RESULTS.md"
    path.write_text(render(rows))
    print(
        f"Wrote {path} ({sum(r.passed is True for r in rows)} pass, "
        f"{sum(r.passed is False for r in rows)} fail, "
        f"{sum(r.achieved == 'NOT RUN' for r in rows)} not run)"
    )
    return path


if __name__ == "__main__":
    main()
