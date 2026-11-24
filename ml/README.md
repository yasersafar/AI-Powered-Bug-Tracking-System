# ML modules

CPU-only models for the three triage steps. Nothing here calls an external AI service (DC-03):
the only network use is the one-time dataset and embedding-model download.

| Module | Method | Code |
|---|---|---|
| Duplicate detection (FR-10) | BM25 Okapi top-50 → `all-MiniLM-L6-v2` cosine re-ranking, incremental index | `duplicate/` |
| Severity (FR-11) | TF-IDF (1-2 grams) → soft-voting ensemble of calibrated LinearSVC, RandomForest, ComplementNB | `severity/` |
| Assignment (FR-12) | CNN-LSTM over report text + component; hybrid cold-start blend with exploration | `assignment/` |

## Reproduce

```bash
make install-ml        # torch (CPU), sentence-transformers, scikit-learn, pandas ...
make data              # download pinned public datasets (~450 MB) and build processed tables
make model-download    # one-time download of all-MiniLM-L6-v2 into ml/artifacts/
make train             # severity ensemble + CNN-LSTMs (about an hour on a laptop CPU)
make eval              # held-out evaluation -> docs/results/*.json|csv|png + RESULTS.md
make test-ml           # unit tests (synthetic data, code behaviour only)
```

Data sources, licences, the join, label mapping and splits are documented in
[`data/README.md`](data/README.md). Results and the analysis of missed targets are in
[`docs/results/RESULTS.md`](../docs/results/RESULTS.md).

## Serving (inside the backend)

`ml/service/` is what the running system uses (Stage 5):

* `context.py` - `TriageContext`, the shared state that flows through the three steps, and
  `TriageResult` with a status and time per step.
* `pipeline.py` - `TriagePipeline`: duplicates -> severity -> assignment, each in a worker
  thread with its own timeout. A likely duplicate boosts the developers who fixed the original;
  a Critical prediction filters out unavailable developers and those at max workload.
* `index.py` - per-project duplicate index (BM25 + cached MiniLM embeddings), incremental.
* `models.py` - loads each artifact independently; a missing one degrades only its step.

The backend adds the database side in `backend/app/services/triage_service.py`.

## Layout

```
common/      text cleaning, time-based split, result writing, plots
data/        download.sh, prepare.py (join + pseudonymise), README
duplicate/   bm25.py, embedder.py, detector.py, fetch_model.py, evaluate.py
severity/    model.py, data.py, train.py, evaluate.py
assignment/  cnn_lstm.py, data.py, train.py, evaluate.py, cold_start.py
service/     context.py, pipeline.py, index.py, models.py (used by the backend)
report.py    builds docs/results/RESULTS.md from the JSON results
artifacts/   trained models (git-ignored; rebuilt by make train)
tests/       unit tests
```
