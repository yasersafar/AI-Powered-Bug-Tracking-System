# Backend (FastAPI)

Python 3.11 · FastAPI · Pydantic v2 · SQLAlchemy 2 · PostgreSQL 16.

## Run locally

From the repository root:

```bash
make install      # creates backend/.venv and installs backend + dev tools
make up           # starts postgres, ntfy, mailpit and the backend container
make test         # pytest with coverage (fails under 70 %, NFR-13)
make lint         # ruff + mypy
```

To run the API outside Docker (hot reload) while the other services run in Docker:

```bash
docker compose up -d db ntfy mailpit
cd backend && .venv/bin/uvicorn app.main:app --reload
```

Interactive API docs: http://localhost:8000/docs · OpenAPI JSON: http://localhost:8000/openapi.json

## Layout

| Path | Purpose |
|---|---|
| `app/api/` | Routers (one module per resource) |
| `app/core/` | Settings, error format, security, DB session, dependencies |
| `app/models/` | SQLAlchemy models |
| `app/schemas/` | Pydantic request/response models |
| `app/services/` | Business logic (bug, audit, notification, triage services) |
| `alembic/` | Database migrations |
| `scripts/` | Seed data, OpenAPI export, load tests |
| `tests/` | Pytest suite |

## AI triage

The three models run inside the API process (CPU only, local files only). They are loaded in a
background thread at start-up; `GET /api/v1/ai/status` shows `loading` / `ready`.

| Endpoint | What it does |
|---|---|
| `POST /api/v1/ai/duplicates` | Possible duplicates in the same project while the user types (FR-10) |
| `POST /api/v1/ai/severity` | Predicted severity with confidence (FR-11) |
| `POST /api/v1/ai/assign` | Top-3 developers with score and reason (FR-12, FR-22) |
| `POST /api/v1/ai/triage` | All three over one shared context; also run on every `POST /bugs` |

Each step has its own time budget (admin settings `*_timeout_ms`). A step that fails, times
out or has no model is returned as `degraded` and the bug is still saved, as `Unclassified`
if severity is missing, with `ai_details.notice` explaining why (NFR-10). Administrators can
switch AI off at run time with the setting `ai_enabled = 0` (the "AI down" demo);
`ML_ENABLED=false` starts the API without models.

Live assignment model: `make train-live` trains the CNN-LSTM on this database's resolution
history (needs at least 2 developers with N resolutions); restart the backend to load it.
Until then the recommender uses similarity to each developer's resolved reports plus profiles.

Performance: `make bench-data` loads 50,000 real Eclipse reports into a separate
`<db>_bench` database, `make bench` measures NFR-01/02/03 and FR-07 over HTTP and
`make test-perf` runs the performance tests. Results: `docs/results/RESULTS.md`.

## Error format

Every error response has the same shape:

```json
{"code": "invalid_transition", "message": "Cannot move Open to Verified", "details": null}
```
