"""CNN-LSTM developer recommender (FR-12): Embedding -> Conv1D -> max-pool -> LSTM -> softmax.

Runs on CPU. `Vocabulary` turns cleaned report text into fixed-length id sequences with the
same tokenizer used everywhere else (ml.common.text.tokenize).
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import torch
from numpy.typing import NDArray
from torch import nn

from ml.common.text import tokenize

PAD, UNK = 0, 1


class Vocabulary:
    def __init__(self, words: list[str], max_len: int) -> None:
        self.words = words
        self.index = {w: i + 2 for i, w in enumerate(words)}
        self.max_len = max_len

    @classmethod
    def build(
        cls, texts: list[str], max_words: int = 30_000, min_count: int = 3, max_len: int = 160
    ) -> "Vocabulary":
        counts = Counter(t for text in texts for t in tokenize(text))
        words = [w for w, c in counts.most_common(max_words) if c >= min_count]
        return cls(words, max_len)

    def __len__(self) -> int:
        return len(self.words) + 2

    def encode(self, texts: list[str]) -> NDArray[np.int64]:
        out = np.zeros((len(texts), self.max_len), dtype=np.int64)
        for row, text in enumerate(texts):
            ids = [self.index.get(t, UNK) for t in tokenize(text)[: self.max_len]]
            out[row, : len(ids)] = ids
        return out


@dataclass(frozen=True)
class ModelConfig:
    vocab_size: int
    num_classes: int
    embedding_dim: int = 128
    conv_channels: int = 128
    kernel_size: int = 5
    lstm_hidden: int = 128
    dropout: float = 0.3


class CNNLSTM(nn.Module):
    def __init__(self, config: ModelConfig) -> None:
        super().__init__()
        self.config = config
        self.embedding = nn.Embedding(config.vocab_size, config.embedding_dim, padding_idx=PAD)
        self.conv = nn.Conv1d(
            config.embedding_dim,
            config.conv_channels,
            config.kernel_size,
            padding=config.kernel_size // 2,
        )
        self.pool = nn.MaxPool1d(2)
        self.lstm = nn.LSTM(config.conv_channels, config.lstm_hidden, batch_first=True)
        self.dropout = nn.Dropout(config.dropout)
        self.output = nn.Linear(config.lstm_hidden, config.num_classes)

    def forward(self, tokens: torch.Tensor) -> torch.Tensor:
        x = self.dropout(self.embedding(tokens))  # (B, T, E)
        x = torch.relu(self.conv(x.transpose(1, 2)))  # (B, C, T)
        x = self.pool(x).transpose(1, 2)  # (B, T/2, C)
        outputs, _ = self.lstm(x)  # (B, T/2, H)
        pooled = outputs.max(dim=1).values  # max over time
        logits: torch.Tensor = self.output(self.dropout(pooled))  # (B, classes) logits
        return logits


class DeveloperRanker:
    """Inference wrapper: text -> probability per known developer."""

    def __init__(self, model: CNNLSTM, vocabulary: Vocabulary, developers: list[str]) -> None:
        self.model = model.eval()
        self.vocabulary = vocabulary
        self.developers = developers

    def probabilities(self, texts: list[str], batch_size: int = 256) -> NDArray[np.float32]:
        encoded = self.vocabulary.encode(texts)
        chunks = []
        with torch.inference_mode():
            for start in range(0, len(encoded), batch_size):
                logits = self.model(torch.from_numpy(encoded[start : start + batch_size]))
                chunks.append(torch.softmax(logits, dim=1).numpy())
        return np.vstack(chunks).astype(np.float32)

    def save(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        torch.save(self.model.state_dict(), directory / "model.pt")
        meta = {
            "config": asdict(self.model.config),
            "developers": self.developers,
            "vocabulary": self.vocabulary.words,
            "max_len": self.vocabulary.max_len,
        }
        (directory / "meta.json").write_text(json.dumps(meta))

    @classmethod
    def load(cls, directory: Path) -> "DeveloperRanker":
        meta = json.loads((directory / "meta.json").read_text())
        model = CNNLSTM(ModelConfig(**meta["config"]))
        model.load_state_dict(
            torch.load(directory / "model.pt", map_location="cpu", weights_only=True)
        )
        return cls(model, Vocabulary(meta["vocabulary"], meta["max_len"]), meta["developers"])
