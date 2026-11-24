"""Model code paths on tiny SYNTHETIC data (not an evaluation)."""

from pathlib import Path

import numpy as np
import torch

from ml.assignment.cnn_lstm import CNNLSTM, DeveloperRanker, ModelConfig, Vocabulary
from ml.assignment.evaluate import ranks_from_scores
from ml.severity.model import Hyperparameters, SeverityClassifier, build_pipeline

TEXTS = ["app crashes and data lost", "typo in label", "slow page load", "server down for all"] * 10
LABELS = ["Critical", "Low", "Medium", "High"] * 10


def test_severity_pipeline_predicts_probabilities(tmp_path: Path) -> None:
    hp = Hyperparameters(min_df=1, rf_trees=10)
    model = SeverityClassifier(build_pipeline(hp).fit(TEXTS, LABELS))
    prediction = model.predict(["the server is down"])[0]
    assert prediction.label in {"Low", "Medium", "High", "Critical"}
    assert abs(sum(prediction.probabilities.values()) - 1) < 1e-3
    assert round(prediction.confidence, 4) == max(prediction.probabilities.values())
    model.save(tmp_path / "m.joblib")
    assert SeverityClassifier.load(tmp_path / "m.joblib").predict(TEXTS[:2])[0].label


def test_vocabulary_encoding() -> None:
    vocab = Vocabulary.build(["alpha beta beta", "beta gamma"], min_count=1, max_len=4)
    encoded = vocab.encode(["beta alpha unknownword", ""])
    assert encoded.shape == (2, 4)
    assert encoded[0, 0] == vocab.index["beta"] and encoded[0, 2] == 1  # UNK
    assert encoded[1].sum() == 0  # padding


def test_cnn_lstm_forward_and_round_trip(tmp_path: Path) -> None:
    torch.manual_seed(0)
    vocab = Vocabulary.build(TEXTS, min_count=1, max_len=12)
    model = CNNLSTM(
        ModelConfig(
            vocab_size=len(vocab), num_classes=3, embedding_dim=8, conv_channels=8, lstm_hidden=8
        )
    )
    logits = model(torch.from_numpy(vocab.encode(TEXTS[:5])))
    assert logits.shape == (5, 3)
    ranker = DeveloperRanker(model, vocab, ["dev_a", "dev_b", "dev_c"])
    probabilities = ranker.probabilities(TEXTS[:5])
    np.testing.assert_allclose(probabilities.sum(axis=1), 1, rtol=1e-5)
    ranker.save(tmp_path)
    np.testing.assert_allclose(
        DeveloperRanker.load(tmp_path).probabilities(TEXTS[:5]), probabilities, rtol=1e-5
    )


def test_rank_of_true_label() -> None:
    scores = np.array([[0.1, 0.7, 0.2], [0.5, 0.5, 0.0], [0.2, 0.3, 0.5]])
    assert ranks_from_scores(scores, np.array([1, 1, 0])).tolist() == [1, 1, 3]
