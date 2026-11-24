# Technology comparison

Why each main technology was chosen, which alternative was considered, and which requirement
drove the decision. Measured numbers come from `docs/results/` (produced by `make eval`,
`make bench` and `make test-perf`); anything not measured in this project is described
qualitatively and marked as such.

## Backend framework: FastAPI vs Flask

| Criterion | Flask | FastAPI (chosen) |
|---|---|---|
| API description (DC-05, NFR-13) | Needs an extension (e.g. flask-smorest or apispec) and hand-written schemas | OpenAPI generated from the route signatures and Pydantic models; exported to `docs/openapi.json` by `make openapi` |
| Input validation (NFR-07) | Manual or via an extension | Pydantic v2 on every request body and query parameter; invalid input returns 422 in the common error format |
| Concurrency model | WSGI, one request per worker thread | ASGI; sync routes run in a thread pool, which suits the CPU-bound triage calls |
| Dependency injection | Not built in | `Depends()` gives one place for the session, current user and role checks (FR-03, NFR-06) |
| Team familiarity | Known from coursework | Similar decorator style; typing is the main new concept |

**Decision:** FastAPI. Linked requirements: DC-05, NFR-06, NFR-07, NFR-13. The generated
3.1 document is converted and validated as OpenAPI 3.0.3 (deviation D-08).

## Database: PostgreSQL vs MySQL

| Criterion | MySQL | PostgreSQL 16 (chosen) |
|---|---|---|
| ACID transactions (DC-04, FR-13) | Yes (InnoDB) | Yes |
| Full-text search (FR-07) | FULLTEXT indexes, natural-language and boolean modes | `tsvector` generated column with weights (title A, description B), GIN index, `websearch_to_tsquery` (phrases, `-exclude`, `OR`) and relevance ranking |
| JSON storage for AI results | JSON type | JSONB with indexing; used for `duplicate_candidates`, `recommended_developers`, `ai_details`, settings |
| Arrays and enums | Enums yes, arrays no | Native arrays (components, languages) and enum types |
| Partial unique index | No | Used to allow only one open assignment per bug |
| CHECK constraints | Enforced since 8.0.16 | Enforced (e.g. audit log "exactly one target", confidence range) |

**Decision:** PostgreSQL. Linked requirements: DC-04, FR-07, FR-13. Measured: keyword search
over 50,000 real bug reports answers in 94 ms at p95 alone and 81 ms under 100 concurrent
users (`load_browse.json`).

## Severity classification: TF-IDF voting ensemble vs fine-tuned BERT

| Criterion | Fine-tuned BERT-style model | TF-IDF + soft-voting ensemble (chosen) |
|---|---|---|
| Hardware | Training realistically needs a GPU; CPU inference of a base-size transformer per report is slower | Trains and predicts on a laptop CPU |
| Latency (NFR-02) | Not measured in this project | 18 ms p95 per report in-process, 29 ms p95 over HTTP (`pipeline_latency_inprocess.json`, `api_latency.json`) |
| Explainability | Low | Word n-gram weights per class; each member model reported separately |
| Data privacy (DC-03) | Runs locally if self-hosted | Runs locally |
| Accuracy on our time-split Eclipse test set | Not evaluated (no GPU budget) | 75.8% (target 85% not met; majority baseline 76.3%), macro-F1 0.296 vs 0.216 (`severity_eclipse.json`) |

**Decision:** the ensemble required by the design, because it meets the latency and
CPU-only constraints. The accuracy target was not met; `docs/results/analysis.md`
explains why (label noise, 76% "normal" reports, strict time split) and lists improvements.
A transformer was not trained, so no claim is made about how it would score here.

## Developer assignment: CNN-LSTM vs a large language model

| Criterion | LLM (hosted API or local) | CNN-LSTM (chosen) |
|---|---|---|
| Privacy (DC-03) | A hosted API would send report text and code context outside the organisation, which is not allowed | Local, CPU |
| Learns from the team's own history | Only through prompting or fine-tuning | Trained on resolution history; one model per database (`make train-live`) |
| Output | Free text that must be parsed into a ranking | A probability per developer, ready to rank |
| Latency (NFR-02) | Not measured | 3 ms p95 in-process; 145 ms p95 for `/ai/assign` over HTTP |
| Cost | Per-token fees (hosted) or a large local model | No runtime cost |
| Measured quality | Not evaluated | Eclipse: 88.9% fewer simulated reassignments than random; live model on the 50k benchmark: 60.7% top-1, 87.6% top-3 (`assignment_eclipse.json`, `assignment_live_bench.json`) |

**Decision:** CNN-LSTM with the cold-start blend (FR-22). Linked requirements: FR-12, FR-22,
DC-03, NFR-02.

## Duplicate detection: BM25 + MiniLM re-ranking vs one method alone

Measured on Eclipse Platform with the realistic pool (every earlier report): the hybrid
(w = 0.7 chosen on the validation period) beats BM25 alone by 6.6 points and a full MiniLM
scan by 4.7 points of Recall@5, at 38 ms p95 over 85,156 reports
(`duplicates_eclipse_platform.json`). Recall@5 is 52.9%, below the 80% target; see the
analysis for the retrieval ceiling. Linked requirements: FR-10, NFR-02.

## VS Code extension vs web application

The design constraint DC-01 fixes the client to the VS Code Extension API: reporting and
triage happen where developers already work. Webviews give rich forms; tree views,
Quick Pick and native notifications give keyboard- and screen-reader-friendly navigation
(NFR-12). The extension never holds model code: inference stays on the backend (DC-02).
