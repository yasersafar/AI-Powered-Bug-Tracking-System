"""Load a realistic benchmark database: 50,000 real Eclipse Platform reports (FR-07, NFR-01..03).

    python -m scripts.bench_data            # -> database <DATABASE_URL name>_bench

Data: the processed Lamkanfi/bugrepo Eclipse table from Stage 4 (ml/data, real public data),
restricted to Platform reports whose MiniLM embedding is already cached from the duplicate
evaluation, so the server does not need to re-encode 50,000 reports at start-up.

* The most recent 50,000 reports become bugs of one project, with their real title,
  description, component, severity and creation date. Fixed reports of the 10 most active
  fixers are Closed and resolved by a developer account standing in for that (pseudonymised)
  fixer, which gives the recommender real resolution history. One extra developer has a
  profile but no history (cold start).
* The next 300 reports (later in time) are not loaded: the load test submits them as new bugs.

Only a database whose name ends in `_bench` is ever written to.
"""

import argparse
import json
import random
import secrets
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models import (
    Bug,
    BugEmbedding,
    BugStatus,
    CloseReason,
    DeveloperProfile,
    ProfileComponent,
    ProfileSkill,
    Project,
    ProjectMember,
    ProjectRole,
    ResolutionHistory,
    Severity,
    User,
    UserRole,
)
from ml.common.paths import PROCESSED

BACKEND_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BACKEND_DIR / "storage" / "bench"
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
REPORTERS = 100
DEVELOPERS = 10
CHUNK = 2000


def bench_url(explicit: str | None) -> str:
    url = make_url(explicit or get_settings().database_url)
    if not str(url.database).endswith("_bench"):
        url = url.set(database=f"{url.database}_bench")
    return url.render_as_string(hide_password=False)


def create_database(url: str) -> None:
    parsed = make_url(url)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.scalar(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": parsed.database}
        )
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = url
    config.attributes["configure_logger"] = False
    command.downgrade(config, "base")  # always start from an empty, current schema
    command.upgrade(config, "head")


def load_reports(total: int, holdout: int) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Most recent Platform reports with a cached embedding, oldest first."""
    from ml.duplicate.evaluate import embeddings_for, load

    platform = load("eclipse_platform")
    vectors = embeddings_for(platform, "eclipse_platform")  # cached by `make eval`
    vector_of = dict(zip(platform["bug_id"].astype(int), range(len(platform)), strict=True))
    frame = pd.read_parquet(
        PROCESSED / "eclipse.parquet",
        columns=[
            "bug_id",
            "component",
            "title",
            "description",
            "created",
            "resolution",
            "severity",
            "fixer",
            "duplicate_of",
        ],
    )
    frame = frame[frame["bug_id"].astype(int).isin(vector_of)]
    frame = frame.sort_values(["created", "bug_id"]).tail(total + holdout).reset_index(drop=True)
    rows = frame.head(total)
    rows_vectors = vectors[[vector_of[int(b)] for b in rows["bug_id"]]]
    return rows, frame.tail(holdout), rows_vectors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-url")
    parser.add_argument("--reports", type=int, default=50_000)
    parser.add_argument("--holdout", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    started = time.perf_counter()
    url = bench_url(args.database_url)
    print(f"benchmark database: {make_url(url).database}")
    create_database(url)
    reports, holdout, vectors = load_reports(args.reports, args.holdout)
    print(
        f"loaded {len(reports):,} reports ({reports['created'].min():%Y-%m-%d} .. "
        f"{reports['created'].max():%Y-%m-%d}); holdout {len(holdout)}"
    )

    engine = create_engine(url)
    password = secrets.token_urlsafe(12) + "aA1!"
    with Session(engine, expire_on_commit=False) as db:
        people = create_people(db, reports, password)
        project = Project(
            name="Eclipse Platform (benchmark)",
            description="50k real reports",
            created_by_id=people["pm"].id,
        )
        db.add(project)
        db.flush()
        db.add(
            ProjectMember(
                project_id=project.id, user_id=people["pm"].id, role=ProjectRole.PROJECT_MANAGER
            )
        )
        for user in people["developers"].values():
            db.add(
                ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.DEVELOPER)
            )
        db.add(
            ProjectMember(
                project_id=project.id, user_id=people["newcomer"].id, role=ProjectRole.DEVELOPER
            )
        )
        for user in people["reporters"]:
            db.add(ProjectMember(project_id=project.id, user_id=user.id, role=ProjectRole.REPORTER))
        db.commit()
        project_id = project.id
        developer_ids = {fixer: u.id for fixer, u in people["developers"].items()}
        reporter_ids = [u.id for u in people["reporters"]]

    insert_bugs(engine, project_id, reports, vectors, developer_ids, reporter_ids, args.seed)
    with Session(engine) as db:
        profiles(db, people, reports)
        db.execute(text("ANALYZE"))
        db.commit()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "credentials.json").write_text(
        json.dumps(
            {
                "password": password,
                "project_id": project_id,
                "manager": people["pm"].email,
                "reporters": [u.email for u in people["reporters"]],
            }
        )
    )
    (OUT_DIR / "holdout.json").write_text(
        json.dumps(
            [
                {
                    "title": str(r.title)[:200] or "(no title)",
                    "description": _description(r),
                    "component": str(r.component),
                }
                for r in holdout.itertuples()
            ]
        )
    )
    print(f"done in {time.perf_counter() - started:.0f}s; credentials in {OUT_DIR}")


def create_people(db: Session, reports: pd.DataFrame, password: str) -> dict[str, Any]:
    hashed = hash_password(password, rounds=get_settings().bcrypt_rounds)
    fixers = reports["fixer"].dropna().value_counts().head(DEVELOPERS).index.tolist()

    def user(email: str, name: str, role: UserRole) -> User:
        account = User(email=email, full_name=name, password_hash=hashed, role=role)
        db.add(account)
        return account

    people: dict[str, Any] = {
        "admin": user("admin@bench.local", "Bench Admin", UserRole.ADMINISTRATOR),
        "pm": user("pm@bench.local", "Bench Manager", UserRole.PROJECT_MANAGER),
        "developers": {
            f: user(f"dev{i + 1}@bench.local", f"Developer {i + 1} ({f})", UserRole.DEVELOPER)
            for i, f in enumerate(fixers)
        },
        "newcomer": user("newcomer@bench.local", "New Developer", UserRole.DEVELOPER),
        "reporters": [
            user(f"load{i + 1}@bench.local", f"Load User {i + 1}", UserRole.REPORTER)
            for i in range(REPORTERS)
        ],
    }
    db.flush()
    return people


def _description(row: Any) -> str:
    description = str(row.description or "").strip()
    if len(description) < 20:  # FR-05 minimum; a few real reports are title-only
        description = (description + " " + str(row.title)).strip().ljust(20, ".")
    return description[:20000]


def insert_bugs(
    engine: Engine,
    project_id: int,
    reports: pd.DataFrame,
    vectors: np.ndarray,
    developer_ids: dict[str, int],
    reporter_ids: list[int],
    seed: int,
) -> None:
    rng = random.Random(seed)  # noqa: S311 (synthetic workflow states, not security)
    bug_rows, plans = [], []
    for row in reports.itertuples():
        created = row.created.to_pydatetime()
        fixer = developer_ids.get(row.fixer) if isinstance(row.fixer, str) else None
        fixed = row.resolution == "FIXED"
        if fixed and fixer is not None:
            status, assignee, reason = BugStatus.CLOSED, fixer, CloseReason.FIXED
        elif row.resolution == "DUPLICATE":
            status, assignee, reason = BugStatus.CLOSED, None, CloseReason.DUPLICATE
        elif row.resolution in ("", None) or rng.random() < 0.15:
            status, assignee, reason = BugStatus.OPEN, None, None
        else:
            status, assignee, reason = BugStatus.CLOSED, None, CloseReason.INVALID
        resolved = created + timedelta(hours=rng.randint(4, 24 * 14))
        severity = Severity(row.severity) if isinstance(row.severity, str) else Severity.MEDIUM
        bug_rows.append(
            {
                "project_id": project_id,
                "reporter_id": rng.choice(reporter_ids),
                "assignee_id": assignee,
                "title": str(row.title)[:200] or "(no title)",
                "description": _description(row),
                "steps_to_reproduce": "See description.",
                "environment": "Eclipse Platform",
                "components": [str(row.component)[:80]],
                "status": status,
                "severity": severity,
                "close_reason": reason,
                "ai_status": "ok",
                "created_at": created,
                "updated_at": resolved if status == BugStatus.CLOSED else created,
                "resolved_at": resolved if reason == CloseReason.FIXED else None,
                "closed_at": resolved if status == BugStatus.CLOSED else None,
            }
        )
        plans.append((fixer if reason == CloseReason.FIXED else None, created, resolved, severity))

    started = time.perf_counter()
    with engine.begin() as conn:
        ids: list[int] = []
        for i in range(0, len(bug_rows), CHUNK):
            result = conn.execute(
                insert(Bug).returning(Bug.id, sort_by_parameter_order=True), bug_rows[i : i + CHUNK]
            )
            ids += [r[0] for r in result]
        conn.execute(
            insert(BugEmbedding),
            [
                {
                    "bug_id": bug_id,
                    "model": EMBEDDING_MODEL,
                    "dimension": int(vectors.shape[1]),
                    "vector": np.asarray(vector, dtype=np.float32).tobytes(),
                }
                for bug_id, vector in zip(ids, vectors, strict=True)
            ],
        )
        history = [
            {
                "bug_id": bug_id,
                "developer_id": fixer,
                "project_id": project_id,
                "severity": severity,
                "components": row["components"],
                "assigned_at": created,
                "resolved_at": resolved,
                "resolution_hours": round((resolved - created).total_seconds() / 3600, 2),
            }
            for bug_id, row, (fixer, created, resolved, severity) in zip(
                ids, bug_rows, plans, strict=True
            )
            if fixer is not None
        ]
        if history:
            conn.execute(insert(ResolutionHistory), history)
    print(
        f"inserted {len(ids):,} bugs, embeddings and {len(history):,} resolutions in "
        f"{time.perf_counter() - started:.0f}s"
    )


def profiles(db: Session, people: dict[str, Any], reports: pd.DataFrame) -> None:
    """Profiles from each fixer's most frequent components (what an admin would enter)."""
    availability = ["Available"] * (DEVELOPERS - 2) + ["Limited", "Unavailable"]

    def profile(user: User, skills: list[str], components: list[str], **fields: Any) -> None:
        db.add(
            DeveloperProfile(
                user_id=user.id,
                languages=["java"],
                skill_rows=[ProfileSkill(skill=s) for s in dict.fromkeys(skills)],
                component_rows=[ProfileComponent(component=c) for c in dict.fromkeys(components)],
                **fields,
            )
        )

    for i, (fixer, user) in enumerate(people["developers"].items()):
        top = reports.loc[reports["fixer"] == fixer, "component"].value_counts().head(4)
        components = [str(c).lower()[:80] for c in top.index]
        resolved = int(
            db.scalar(
                text("SELECT count(*) FROM resolution_history WHERE developer_id = :d"),
                {"d": user.id},
            )
            or 0
        )
        profile(
            user,
            ["java", "swt", *components[:2]],
            components,
            availability=availability[i],
            max_workload=8,
            resolved_count=resolved,
            is_cold_start=resolved < 10,
        )
    profile(
        people["newcomer"],
        ["java", "ui", "swt", "accessibility"],
        ["ui", "swt"],
        availability="Available",
        max_workload=5,
    )
    db.commit()


if __name__ == "__main__":
    main()
