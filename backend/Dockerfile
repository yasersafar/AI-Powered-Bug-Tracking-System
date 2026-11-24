# Build context is the repository root (see docker-compose.yml), so the image
# can include both backend/ and ml/ (the backend imports ml.service in Stage 5).
FROM python:3.11-slim-trixie

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/srv

# libmagic: real MIME-type detection for attachments (FR-14)
RUN apt-get update \
    && apt-get install -y --no-install-recommends libmagic1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/attachments \
    && chown appuser:appuser /data/attachments

WORKDIR /srv/backend
# ML runtime first (large, rarely changes): CPU-only PyTorch, then the rest of ml/requirements.
COPY ml/requirements.txt /tmp/ml-requirements.txt
RUN pip install "torch~=2.15" --index-url https://download.pytorch.org/whl/cpu \
    && pip install -r /tmp/ml-requirements.txt

COPY backend/pyproject.toml backend/README.md ./
COPY backend/app ./app
RUN pip install .
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/scripts ./scripts

# Model code only; the trained artifacts are mounted read-only (see docker-compose.yml).
COPY ml /srv/ml
ENV ML_ARTIFACTS_DIR=/srv/ml/artifacts \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    TOKENIZERS_PARALLELISM=false

USER appuser
EXPOSE 8000
# Apply pending migrations, then serve. `exec` makes uvicorn PID 1 so it receives SIGTERM.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers"]
