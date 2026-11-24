"""Filesystem locations shared by the ML scripts."""

from pathlib import Path

ML_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ML_ROOT.parent
RAW = ML_ROOT / "data" / "raw"
PROCESSED = ML_ROOT / "data" / "processed"
ARTIFACTS = ML_ROOT / "artifacts"
RESULTS = REPO_ROOT / "docs" / "results"
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_MODEL_DIR = ARTIFACTS / "all-MiniLM-L6-v2"
