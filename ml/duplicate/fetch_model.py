"""One-time download of the sentence-embedding model into ml/artifacts/ (needs network once).

python -m ml.duplicate.fetch_model
"""

from ml.common.paths import EMBEDDING_MODEL_DIR, EMBEDDING_MODEL_NAME


def main() -> None:
    if (EMBEDDING_MODEL_DIR / "config.json").exists():
        print(f"Already present: {EMBEDDING_MODEL_DIR}")
        return
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL_NAME, device="cpu")
    model.save(str(EMBEDDING_MODEL_DIR))
    print(f"Saved {EMBEDDING_MODEL_NAME} -> {EMBEDDING_MODEL_DIR}")


if __name__ == "__main__":
    main()
