"""Latency and load tests against a running backend (NFR-01, NFR-02, NFR-03, FR-07).

    python -m scripts.loadtest all --base-url http://127.0.0.1:8001

Needs the benchmark database from `python -m scripts.bench_data` (50,000 real Eclipse
reports) and a server using it (`make bench` starts one in Docker). Every number is measured
from the client side over HTTP and written to docs/results/*.json together with how it was
measured; nothing is estimated.

Load model (fixed before measuring, not tuned afterwards):
* "N concurrent users" = N virtual users active at the same time, each repeating
  request -> random think time. Submitting users think 2-8 s between bug reports (an
  aggressive pace: a person needs minutes to write a report); browsing users think 1-3 s.
* NFR-03 compares the latency of a bug submission under 50 concurrent users with the
  latency of the same submissions made by a single user. A burst (all 50 users press
  "submit" at the same instant) is reported as extra information.
"""

import argparse
import asyncio
import json
import platform
import random
import re
import subprocess
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx2 as httpx
import numpy as np

BACKEND_DIR = Path(__file__).resolve().parents[1]
BENCH_DIR = BACKEND_DIR / "storage" / "bench"
RESULTS = BACKEND_DIR.parent / "docs" / "results"
API = "/api/v1"
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
SEARCH_WORDS = (
    "editor",
    "view",
    "crash",
    "NPE",
    "dialog",
    "preferences",
    "workspace",
    "perspective",
    '"content assist"',
    "refresh",
    "build -ant",
    "toolbar",
)
STATUSES = ("Open", "InProgress", "Resolved", "Closed")
SEVERITIES = ("Low", "Medium", "High", "Critical")
# uvicorn closes idle keep-alive connections after 5 s. A client that keeps them for the same
# 5 s (the httpx default) sometimes reuses a connection the server is closing at that moment.
# Real clients drop idle connections earlier (or retry idempotent requests); so does this one.
KEEPALIVE_S = 3.0


# --------------------------------------------------------------------------- helpers
@dataclass
class Recorder:
    samples: dict[str, list[float]] = field(default_factory=dict)
    errors: dict[str, int] = field(default_factory=dict)
    degraded: dict[str, int] = field(default_factory=dict)
    failures: dict[str, int] = field(default_factory=dict)  # what went wrong, by kind

    async def timed(
        self, name: str, call: Awaitable[httpx.Response], expect: int = 200
    ) -> httpx.Response | None:
        started = time.perf_counter()
        try:
            response = await call  # not started before this point, so timing is exact
        except httpx.HTTPError as exc:
            self.errors[name] = self.errors.get(name, 0) + 1
            kind = f"{name}: {type(exc).__name__}"
            self.failures[kind] = self.failures.get(kind, 0) + 1
            return None
        elapsed = (time.perf_counter() - started) * 1000
        if response.status_code != expect:
            self.errors[name] = self.errors.get(name, 0) + 1
            kind = f"{name}: HTTP {response.status_code}"
            self.failures[kind] = self.failures.get(kind, 0) + 1
            return response
        self.samples.setdefault(name, []).append(elapsed)
        if response.headers.get("content-type", "").startswith("application/json"):
            body = response.json()
            if isinstance(body, dict) and body.get("ai_status") == "degraded":
                self.degraded[name] = self.degraded.get(name, 0) + 1
        return response

    def summary(self) -> dict[str, Any]:
        return {
            name: stats(values, self.errors.get(name, 0), self.degraded.get(name, 0))
            for name, values in sorted(self.samples.items())
        }


def stats(values: list[float], errors: int = 0, degraded: int = 0) -> dict[str, Any]:
    data = np.asarray(values, dtype=float)
    if data.size == 0:
        return {"count": 0, "errors": errors}
    return {
        "count": int(data.size),
        "errors": errors,
        "ai_degraded": degraded,
        "mean_ms": round(float(data.mean()), 1),
        "p50_ms": round(float(np.percentile(data, 50)), 1),
        "p95_ms": round(float(np.percentile(data, 95)), 1),
        "p99_ms": round(float(np.percentile(data, 99)), 1),
        "max_ms": round(float(data.max()), 1),
    }


def clean(text: str) -> str:
    return CONTROL.sub(" ", text)


def report(item: dict[str, str]) -> dict[str, str]:
    title = clean(item["title"]).replace("\n", " ").strip()
    return {
        "title": title if len(title) >= 5 else f"{title} (bug)",
        "description": clean(item["description"]),
    }


def submission(project_id: int, item: dict[str, str]) -> dict[str, Any]:
    return {
        **report(item),
        "project_id": project_id,
        "steps_to_reproduce": "See description.",
        "environment": "Eclipse Platform",
        "components": [item["component"][:80]],
    }


async def login(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post(
        f"{API}/auth/login", data={"username": email, "password": password}
    )
    response.raise_for_status()
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def load_inputs() -> tuple[dict[str, Any], list[dict[str, str]]]:
    credentials = json.loads((BENCH_DIR / "credentials.json").read_text())
    holdout = json.loads((BENCH_DIR / "holdout.json").read_text())
    return credentials, holdout


async def server_info(client: httpx.AsyncClient, headers: dict[str, str]) -> dict[str, Any]:
    status = (await client.get(f"{API}/ai/status", headers=headers)).json()
    total = (await client.get(f"{API}/bugs", params={"page_size": 1}, headers=headers)).json()
    return {"ai": status, "bugs_in_database": total["total"]}


def provenance(base_url: str, server: dict[str, Any], method: str) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
            cwd=BACKEND_DIR,
        ).stdout.strip()
    except OSError:
        commit = "unknown"
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "client_machine": f"{platform.system()} {platform.machine()}",
        "base_url": base_url,
        "git_commit": commit,
        "server": server,
        "method": method,
    }


def write(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=2))
    print(f"wrote {path}")
    return path


# --------------------------------------------------------------------------- NFR-02
async def latency(base_url: str, reports: int = 200, save: bool = True) -> dict[str, Any]:
    """Sequential (one user): time of each AI endpoint on held-out real reports."""
    credentials, holdout = load_inputs()
    project = credentials["project_id"]
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        headers = await login(client, credentials["manager"], credentials["password"])
        server = await server_info(client, headers)
        recorder, warmup = Recorder(), Recorder()
        combined: list[float] = []
        server_steps: dict[str, list[float]] = {"duplicates": [], "severity": [], "assignment": []}
        for i, item in enumerate(holdout[: reports + 10]):
            rec = warmup if i < 10 else recorder
            text = report(item)
            draft = {**text, "project_id": project}
            dup = await rec.timed(
                "ai_duplicates",
                client.post(f"{API}/ai/duplicates", json=draft, headers=headers),
            )
            sev = await rec.timed(
                "ai_severity", client.post(f"{API}/ai/severity", json=text, headers=headers)
            )
            await rec.timed(
                "ai_assign",
                client.post(
                    f"{API}/ai/assign",
                    json={**draft, "components": [item["component"][:80]]},
                    headers=headers,
                ),
            )
            full = await rec.timed(
                "ai_triage",
                client.post(
                    f"{API}/ai/triage",
                    json={**draft, "components": [item["component"][:80]]},
                    headers=headers,
                ),
            )
            if i >= 10 and dup is not None and sev is not None:
                combined.append(
                    recorder.samples["ai_duplicates"][-1] + recorder.samples["ai_severity"][-1]
                )
            if i >= 10 and full is not None and full.status_code == 200:
                for name, step in full.json()["steps"].items():
                    server_steps[name].append(step["elapsed_ms"])
    summary = recorder.summary()
    both = stats(combined)
    result: dict[str, Any] = {
        "provenance": provenance(
            base_url,
            server,
            "Sequential requests from one user over "
            "HTTP on 200 held-out Eclipse Platform reports (10 warm-up "
            "requests not counted). Client-side wall time.",
        ),
        "reports": reports,
        "endpoints": summary,
        "failures": recorder.failures,
        "duplicates_plus_severity": both,
        "server_side_step_ms_in_triage": {k: stats(v) for k, v in server_steps.items()},
        "targets": {
            "duplicates_plus_severity_p95_ms": 1500,
            "assignment_p95_ms": 3000,
        },
    }
    result["pass"] = {
        "duplicates_plus_severity": both["p95_ms"] <= 1500,
        "assignment": summary["ai_assign"]["p95_ms"] <= 3000,
        "full_triage_within_assignment_budget": summary["ai_triage"]["p95_ms"] <= 3000,
    }
    if save:
        write("api_latency.json", result)
    return result


# --------------------------------------------------------------------------- NFR-03
async def submissions(
    base_url: str,
    users: int = 50,
    duration: float = 90.0,
    baseline: int = 60,
    seed: int = 1,
    save: bool = True,
) -> dict[str, Any]:
    credentials, holdout = load_inputs()
    project = credentials["project_id"]
    rng = random.Random(seed)  # noqa: S311 (load pattern, not security)
    limits = httpx.Limits(
        max_connections=users + 10,
        max_keepalive_connections=users + 10,
        keepalive_expiry=KEEPALIVE_S,
    )
    async with httpx.AsyncClient(base_url=base_url, timeout=60, limits=limits) as client:
        logins = await asyncio.gather(
            *[login(client, e, credentials["password"]) for e in credentials["reporters"][:users]]
        )
        server = await server_info(client, logins[0])

        def post(headers: dict[str, str], item: dict[str, str]) -> Awaitable[httpx.Response]:
            return client.post(f"{API}/bugs", json=submission(project, item), headers=headers)

        # Baseline: one user, one submission at a time.
        single = Recorder()
        for i in range(baseline + 5):
            rec = single if i >= 5 else Recorder()
            await rec.timed("submit", post(logins[0], holdout[i % len(holdout)]), expect=201)

        # Load: `users` users submitting concurrently with think time.
        loaded = Recorder()
        stop_at = time.perf_counter() + duration

        async def user(index: int) -> None:
            local = random.Random(seed + index)  # noqa: S311
            await asyncio.sleep(local.uniform(0, 8))  # users do not start in lockstep
            while time.perf_counter() < stop_at:
                item = holdout[local.randrange(len(holdout))]
                await loaded.timed("submit", post(logins[index], item), expect=201)
                await asyncio.sleep(local.uniform(2, 8))

        started = time.perf_counter()
        await asyncio.gather(*[user(i) for i in range(users)])
        elapsed = time.perf_counter() - started

        # Burst (information only): every user submits at the same instant.
        burst = Recorder()
        await asyncio.gather(
            *[
                burst.timed(
                    "submit", post(logins[i], holdout[rng.randrange(len(holdout))]), expect=201
                )
                for i in range(users)
            ]
        )

    base, load, spike = (r.summary()["submit"] for r in (single, loaded, burst))
    degradation = {
        "p50": round(load["p50_ms"] / base["p50_ms"] - 1, 4),
        "p95": round(load["p95_ms"] / base["p95_ms"] - 1, 4),
        "mean": round(load["mean_ms"] / base["mean_ms"] - 1, 4),
    }
    result = {
        "provenance": provenance(
            base_url,
            server,
            (
                f"POST /bugs with held-out Eclipse reports (full triage on every submission). "
                f"Baseline: 1 user, {baseline} sequential submissions. Load: {users} concurrent "
                f"users for {duration:.0f}s, think time uniform 2-8 s. Degradation = load / "
                "baseline - 1 of the same percentile."
            ),
        ),
        "baseline_single_user": base,
        "concurrent_users": users,
        "load": {
            **load,
            "duration_s": round(elapsed, 1),
            "throughput_per_s": round(load["count"] / elapsed, 2),
        },
        "degradation": degradation,
        "failures": {**single.failures, **loaded.failures},
        "burst_all_users_at_once_info_only": spike,
        "target": "p95 degradation < 10%, no failed submissions",
        "pass": degradation["p95"] < 0.10 and load["errors"] == 0,
    }
    if save:
        write("load_submissions.json", result)
    return result


# --------------------------------------------------------------------------- NFR-01 + FR-07
def browse_actions(
    project: int, ids: list[int], rng: random.Random
) -> tuple[str, str, dict[str, Any]]:
    choice = rng.random()
    if choice < 0.30:
        return "list_page", f"{API}/bugs", {"project_id": project, "page": rng.randint(1, 200)}
    if choice < 0.50:
        return (
            "keyword_search",
            f"{API}/bugs",
            {"project_id": project, "q": rng.choice(SEARCH_WORDS), "sort": "relevance"},
        )
    if choice < 0.65:
        return (
            "filtered_search",
            f"{API}/bugs",
            {
                "project_id": project,
                "status": rng.choice(STATUSES),
                "severity": rng.choice(SEVERITIES),
                "created_from": "2008-01-01T00:00:00Z",
            },
        )
    if choice < 0.95:
        return "bug_detail", f"{API}/bugs/{rng.choice(ids)}", {}
    return "dashboard", f"{API}/projects/{project}/dashboard", {}


async def browse(
    base_url: str, users: int = 100, duration: float = 90.0, seed: int = 2, save: bool = True
) -> dict[str, Any]:
    credentials, _ = load_inputs()
    project = credentials["project_id"]
    limits = httpx.Limits(
        max_connections=users + 10,
        max_keepalive_connections=users + 10,
        keepalive_expiry=KEEPALIVE_S,
    )
    async with httpx.AsyncClient(base_url=base_url, timeout=60, limits=limits) as client:
        manager = await login(client, credentials["manager"], credentials["password"])
        logins = [manager]
        for chunk in range(0, users - 1, 20):  # bcrypt logins in small batches
            logins += await asyncio.gather(
                *[
                    login(client, e, credentials["password"])
                    for e in credentials["reporters"][chunk : min(chunk + 20, users - 1)]
                ]
            )
        server = await server_info(client, manager)
        page = (
            await client.get(
                f"{API}/bugs", params={"project_id": project, "page_size": 100}, headers=manager
            )
        ).json()
        ids = [b["id"] for b in page["items"]] + list(range(1, server["bugs_in_database"], 97))

        # FR-07 alone: sequential searches on 50k bugs, before any load.
        sequential = Recorder()
        rng = random.Random(seed)  # noqa: S311
        for _ in range(100):
            name, url, params = browse_actions(project, ids, rng)
            if name in ("keyword_search", "filtered_search", "list_page"):
                await sequential.timed(name, client.get(url, params=params, headers=manager))

        recorder = Recorder()
        stop_at = time.perf_counter() + duration

        async def user(index: int) -> None:
            local = random.Random(seed * 1000 + index)  # noqa: S311
            await asyncio.sleep(local.uniform(0, 3))
            while time.perf_counter() < stop_at:
                name, url, params = browse_actions(project, ids, local)
                await recorder.timed(name, client.get(url, params=params, headers=logins[index]))
                await asyncio.sleep(local.uniform(1, 3))

        started = time.perf_counter()
        await asyncio.gather(*[user(i) for i in range(users)])
        elapsed = time.perf_counter() - started

    under_load = recorder.summary()
    alone = sequential.summary()
    total = sum(v["count"] for v in under_load.values())
    result = {
        "provenance": provenance(
            base_url,
            server,
            (
                f"{users} concurrent users for {duration:.0f}s, think time uniform 1-3 s; actions: "
                "list page 30%, keyword search (tsvector, relevance) 20%, filtered search 15%, "
                "bug detail 30%, project dashboard 5%. FR-07 also measured alone (100 sequential "
                "searches) before the load."
            ),
        ),
        "concurrent_users": users,
        "requests": total,
        "throughput_per_s": round(total / elapsed, 1),
        "under_load": under_load,
        "failures": recorder.failures,
        "search_alone_fr07": alone,
        "targets": {"nfr01_p95_ms": 2000, "fr07_p95_ms": 2000},
    }
    result["pass"] = {
        "nfr01_all_endpoints_p95_within_2s": all(
            v["p95_ms"] <= 2000 and v["errors"] == 0 for v in under_load.values()
        ),
        "fr07_search_p95_within_2s_alone": all(v["p95_ms"] <= 2000 for v in alone.values()),
        "fr07_search_p95_within_2s_under_load": all(
            under_load[k]["p95_ms"] <= 2000 for k in ("keyword_search", "filtered_search")
        ),
    }
    if save:
        write("load_browse.json", result)
    return result


async def wait_ready(base_url: str, timeout: float = 600.0) -> dict[str, Any]:
    """The server answers /health at once but loads models in the background."""
    credentials, _ = load_inputs()
    deadline = time.perf_counter() + timeout
    async with httpx.AsyncClient(base_url=base_url, timeout=30) as client:
        headers = await login(client, credentials["manager"], credentials["password"])
        while True:
            status: dict[str, Any] = (await client.get(f"{API}/ai/status", headers=headers)).json()
            if status["state"] in ("ready", "failed", "disabled") or time.perf_counter() > deadline:
                return status
            await asyncio.sleep(2)


def main() -> None:
    parser = argparse.ArgumentParser(description="NFR-01/02/03 and FR-07 measurements")
    parser.add_argument("test", choices=["latency", "submissions", "browse", "all"])
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    parser.add_argument("--duration", type=float, default=90.0)
    args = parser.parse_args()
    status = asyncio.run(wait_ready(args.base_url))
    print("server AI state:", status["state"], status["models"], status["indexed_reports"])
    if args.test in ("latency", "all"):
        r = asyncio.run(latency(args.base_url))
        print(
            "NFR-02",
            r["pass"],
            r["duplicates_plus_severity"]["p95_ms"],
            r["endpoints"]["ai_assign"]["p95_ms"],
        )
    if args.test in ("browse", "all"):
        r = asyncio.run(browse(args.base_url, duration=args.duration))
        print("NFR-01/FR-07", r["pass"])
    if args.test in ("submissions", "all"):
        r = asyncio.run(submissions(args.base_url, duration=args.duration))
        print("NFR-03", r["pass"], r["degradation"])


if __name__ == "__main__":
    main()
