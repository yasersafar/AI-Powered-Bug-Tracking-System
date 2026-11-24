"""Train the CNN-LSTM recommender on THIS system's resolution history (FR-12, FR-22).

    python -m scripts.train_assignment                 # database from DATABASE_URL
    python -m scripts.train_assignment --database-url postgresql+psycopg://.../bugtracker_bench

The Stage 4 models were trained on Bugzilla developers, who are not users of this system.
This script trains the same architecture on the bugs that this system's developers have
resolved (`resolution_history`, reopened resolutions excluded), so its classes are user ids.
Only developers with at least N resolutions (N = the admin setting `cold_start_threshold`)
become classes; everybody else is scored by history similarity or, with no history, by
profile only (cold start).

Split by resolution time: oldest 70% train, next 10% validation (early stopping), newest 20%
test (reported, never used for training decisions). The model is saved per database in
ml/artifacts/assignment/live/<database>/ and loaded when the backend starts.
"""

import argparse
import json
import time
from collections import Counter
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Bug, ResolutionHistory
from app.services import settings_service
from ml.assignment.train import fit, top_k_accuracy
from ml.common.paths import ARTIFACTS, RESULTS
from ml.service.context import TriageContext
from ml.service.models import live_model_dir

MIN_SAMPLES = 100


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--database-url")
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--results-name", help="also write docs/results/<name>.json")
    args = parser.parse_args()

    url = args.database_url or get_settings().database_url
    database = str(make_url(url).database)
    engine = create_engine(url)
    with Session(engine) as db:
        threshold = int(settings_service.get_value(db, "cold_start_threshold"))
        rows = db.execute(
            select(
                ResolutionHistory.developer_id,
                Bug.title,
                Bug.description,
                Bug.components,
            )
            .join(Bug, Bug.id == ResolutionHistory.bug_id)
            .where(ResolutionHistory.reopened.is_(False))
            .order_by(ResolutionHistory.resolved_at, ResolutionHistory.id)
        ).all()
    engine.dispose()

    counts = Counter(r.developer_id for r in rows)
    developers = sorted(d for d, n in counts.items() if n >= threshold)
    samples = [r for r in rows if r.developer_id in set(developers)]
    if len(developers) < 2 or len(samples) < MIN_SAMPLES:
        print(
            f"[{database}] not enough history for a live CNN-LSTM: {len(developers)} developers "
            f"with >= {threshold} resolutions, {len(samples)} resolutions (need 2 and "
            f"{MIN_SAMPLES}). The recommender keeps using history similarity + profiles."
        )
        return

    texts = [
        TriageContext(
            title=r.title, description=r.description, project_id=0, components=r.components
        ).assignment_text
        for r in samples
    ]
    index = {d: i for i, d in enumerate(developers)}
    labels = [index[r.developer_id] for r in samples]
    a, b = int(len(samples) * 0.7), int(len(samples) * 0.8)
    result = fit(
        texts[:a],
        labels[:a],
        texts[a:b],
        labels[a:b],
        [str(d) for d in developers],
        args.epochs,
        args.seed,
    )
    probabilities = result.ranker.probabilities(texts[b:])
    test_labels = np.array(labels[b:])
    out = live_model_dir(ARTIFACTS, database)
    result.ranker.save(out)
    summary = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "database": database,
        "developers": len(developers),
        "min_resolutions_per_developer": threshold,
        "resolutions": {"train": a, "validation": b - a, "test": len(samples) - b},
        "epochs_run": len(result.history),
        "history": result.history,
        "training_seconds": round(result.seconds, 1),
        "test_top1": round(top_k_accuracy(probabilities, test_labels, 1), 4),
        "test_top3": round(top_k_accuracy(probabilities, test_labels, 3), 4),
        "majority_class_top1": round(
            Counter(labels[b:]).most_common(1)[0][1] / (len(samples) - b), 4
        ),
        "method": "Time split by resolution date: 70% train / 10% validation (early stopping) "
        "/ 20% test. Classes = developers of this database with >= N resolutions.",
    }
    (out / "training.json").write_text(json.dumps(summary, indent=2))
    if args.results_name:
        (RESULTS / f"{args.results_name}.json").write_text(json.dumps(summary, indent=2))
    print(
        f"[{database}] {len(developers)} developers, {len(samples)} resolutions, "
        f"test top-1 {summary['test_top1']:.3f} / top-3 {summary['test_top3']:.3f} "
        f"(majority {summary['majority_class_top1']:.3f}); saved to {out}. "
        "Restart the backend to load it."
    )


if __name__ == "__main__":
    started = time.perf_counter()
    main()
    print(f"done in {time.perf_counter() - started:.0f}s")
