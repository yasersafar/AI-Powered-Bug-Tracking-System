"""Local sentence-embedding model (all-MiniLM-L6-v2), CPU only (DC-03).

The model is downloaded once with `python -m ml.duplicate.fetch_model` into ml/artifacts/ and
always loaded from that directory with Hugging Face offline mode on, so no text is ever sent
to an external service at run time.
"""

import os
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

from ml.common.paths import EMBEDDING_MODEL_DIR


class Embedder:
    def __init__(self, model_dir: Path = EMBEDDING_MODEL_DIR, batch_size: int = 64) -> None:
        if not (model_dir / "config.json").exists():
            raise FileNotFoundError(
                f"Embedding model missing at {model_dir}; run `python -m ml.duplicate.fetch_model`"
            )
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(str(model_dir), device="cpu")
        self.batch_size = batch_size
        size = (
            getattr(self.model, "get_embedding_dimension", None)
            or self.model.get_sentence_embedding_dimension
        )
        self.dimension = int(size() or 384)

    def encode(self, texts: list[str], show_progress: bool = False) -> NDArray[np.float32]:
        vectors = self.model.encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=show_progress,
        )
        return np.asarray(vectors, dtype=np.float32)
