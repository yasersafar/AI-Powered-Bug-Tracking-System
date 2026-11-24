# Developer commands. Run `make help` for the list.
# Requires: Docker (Compose v2), Python 3.11, Node.js 20+.

SHELL := /bin/bash
.DEFAULT_GOAL := help

PYTHON      ?= python3.11
VENV        := backend/.venv
VENV_PY     := $(VENV)/bin/python
COMPOSE     := docker compose
MOZILLA_SAMPLE ?= 80000

.PHONY: help env install install-backend install-extension up down nuke ps logs migrate test-live openapi diagrams seed seed-reset \
        install-ml data model-download train eval test-ml train-live bench-data bench-up bench-down bench test-perf \
        test test-backend lint lint-backend lint-extension format build-extension test-extension package-extension clean

help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | sort | \
		awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# --------------------------------------------------------------------------- setup
env: ## Create/complete .env with generated secrets (JWT key, ntfy token, seed password)
	@$(PYTHON) backend/scripts/init_env.py

$(VENV_PY):
	$(PYTHON) -m venv $(VENV)
	$(VENV_PY) -m pip install --upgrade pip

install-backend: $(VENV_PY) ## Install backend + dev tools + ML runtime (CPU) into backend/.venv
	$(VENV_PY) -m pip install "torch~=2.15" --index-url https://download.pytorch.org/whl/cpu
	$(VENV_PY) -m pip install -r ml/requirements.txt -e "backend[dev]"

install-extension: ## Install extension npm dependencies
	cd extension && npm ci

install: env install-backend install-extension ## Install everything for local development

# --------------------------------------------------------------------------- services
up: env ## Build and start postgres, ntfy, mailpit and backend; wait until healthy
	$(COMPOSE) up -d --build --wait
	@echo ""
	@echo "  API docs : http://localhost:$${BACKEND_PORT:-8000}/docs"
	@echo "  ntfy     : http://localhost:$${NTFY_PORT:-8080}"
	@echo "  Mailpit  : http://localhost:$${MAILPIT_UI_PORT:-8025}"

down: ## Stop all services (data volumes are kept)
	$(COMPOSE) down

nuke: ## Stop all services AND delete database, ntfy and attachment volumes
	$(COMPOSE) down -v

ps: ## Show service status
	$(COMPOSE) ps

logs: ## Follow service logs
	$(COMPOSE) logs -f --tail=100

openapi: ## Export docs/openapi.json (OpenAPI 3.0.3) and docs/openapi-3.1.json, both validated
	cd backend && PYTHONPATH=.. .venv/bin/python -m scripts.export_openapi

diagrams: ## Regenerate the ERD from the models and render docs/diagrams/*.puml to PNG (needs plantuml)
	cd backend && PYTHONPATH=.. .venv/bin/python -m scripts.export_erd
	cd docs/diagrams && plantuml -tpng *.puml

seed: ## Load demo data into the running stack (refuses if data exists)
	$(COMPOSE) exec backend python -m scripts.seed

seed-reset: ## DELETE all application data, then load demo data
	$(COMPOSE) exec backend python -m scripts.seed --reset

migrate: ## Apply database migrations (the backend container also does this on start)
	cd backend && .venv/bin/alembic upgrade head

# --------------------------------------------------------------------------- ML (Stage 4)
# Cap CPU threads for training/evaluation to keep laptops cool (results do not depend on it).
ML_THREADS ?= 4
ML_PY := OMP_NUM_THREADS=$(ML_THREADS) MKL_NUM_THREADS=$(ML_THREADS) TOKENIZERS_PARALLELISM=false $(VENV_PY)

install-ml: $(VENV_PY) ## Install ML training/inference dependencies (CPU) into backend/.venv
	$(VENV_PY) -m pip install -r ml/requirements-train.txt

data: ## Download the public datasets (~450 MB) and build ml/data/processed/
	bash ml/data/download.sh
	$(ML_PY) -m ml.data.prepare

model-download: ## One-time download of all-MiniLM-L6-v2 into ml/artifacts/ (then offline)
	$(ML_PY) -m ml.duplicate.fetch_model

train: ## Train severity ensemble and CNN-LSTM models (CPU, roughly an hour)
	$(ML_PY) -m ml.severity.train --ecosystem eclipse
	$(ML_PY) -m ml.assignment.train --ecosystem eclipse
	$(ML_PY) -m ml.assignment.train --ecosystem mozilla --sample $(MOZILLA_SAMPLE)

eval: ## Evaluate all models on the held-out test periods -> docs/results/
	$(ML_PY) -m ml.severity.evaluate --ecosystem eclipse
	$(ML_PY) -m ml.duplicate.evaluate --dataset eclipse_platform
	$(ML_PY) -m ml.duplicate.evaluate --dataset eclipse_jdt
	$(ML_PY) -m ml.assignment.evaluate --ecosystem eclipse
	$(ML_PY) -m ml.assignment.evaluate --ecosystem mozilla --sample $(MOZILLA_SAMPLE)
	$(ML_PY) -m ml.report

test-ml: ## ML unit tests
	cd ml && ../$(VENV_PY) -m pytest

# --------------------------------------------------------------------------- performance (Stage 5)
BENCH_PORT ?= 8001
BENCH_URL := http://127.0.0.1:$(BENCH_PORT)
BENCH_PY := cd backend && PYTHONPATH=.. OMP_NUM_THREADS=$(ML_THREADS) .venv/bin/python

train-live: ## Train the live CNN-LSTM on this database's resolution history (restart backend after)
	$(BENCH_PY) -m scripts.train_assignment

bench-data: ## Load 50,000 real Eclipse reports into <db>_bench (needs make up, data, eval)
	$(BENCH_PY) -m scripts.bench_data

bench-up: ## Start the benchmark backend (port 8001) on the benchmark database
	$(COMPOSE) build backend
	$(COMPOSE) --profile bench up -d --wait backend-bench

bench-down: ## Stop the benchmark backend
	$(COMPOSE) --profile bench stop backend-bench

bench: bench-up ## NFR-01/02/03 + FR-07 measurements -> docs/results/ (about 6 minutes)
	$(BENCH_PY) -m scripts.loadtest all --base-url $(BENCH_URL)
	$(MAKE) bench-down
	$(ML_PY) -m ml.report

test-perf: ## Performance tests: NFR-02 in-process + NFR-01/03 against a running bench-up
	cd backend && BENCH_URL=$(BENCH_URL) OMP_NUM_THREADS=$(ML_THREADS) .venv/bin/pytest -m perf -v --no-cov

# --------------------------------------------------------------------------- quality
test: test-backend test-ml ## Run all test suites

test-backend: ## Backend tests with coverage (needs `make up` for PostgreSQL; NFR-13)
	cd backend && .venv/bin/pytest --cov --cov-report=term --cov-report=xml

test-live: ## Deliver real notifications through the running ntfy + Mailpit (needs make up)
	cd backend && .venv/bin/pytest -m live -v --no-cov

lint: lint-backend lint-extension ## Run all linters and type checkers

lint-backend: ## Ruff (lint + format check) and mypy
	$(VENV)/bin/ruff check backend ml
	$(VENV)/bin/ruff format --check backend ml
	cd backend && .venv/bin/mypy

lint-extension: ## ESLint, TypeScript type check and Prettier check
	cd extension && npm run lint && npm run typecheck && npm run format:check

format: ## Auto-format Python and TypeScript
	$(VENV)/bin/ruff format backend ml
	$(VENV)/bin/ruff check --fix backend ml
	cd extension && npm run format

build-extension: ## Bundle the VS Code extension
	cd extension && npm run build

test-extension: ## Extension tests inside VS Code (downloads VS Code once into extension/.vscode-test)
	cd extension && npm test

package-extension: ## Build the installable extension/ai-bug-tracker-<version>.vsix
	cd extension && npm run package

clean: ## Remove caches and build output
	find . -type d \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) -prune -exec rm -rf {} +
	rm -rf backend/htmlcov backend/coverage.xml backend/.coverage extension/dist
