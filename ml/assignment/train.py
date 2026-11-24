"""Train the CNN-LSTM on historical fixes (CPU), early-stopping on the validation period.

python -m ml.assignment.train --ecosystem eclipse
python -m ml.assignment.train --ecosystem mozilla --sample 80000
"""

import argparse
import json
import time
from dataclasses import dataclass

import numpy as np
import torch
from torch import nn

from ml.assignment import data as assignment_data
from ml.assignment.cnn_lstm import CNNLSTM, DeveloperRanker, ModelConfig, Vocabulary
from ml.common.paths import ARTIFACTS


def top_k_accuracy(probabilities: np.ndarray, labels: np.ndarray, k: int) -> float:
    top = np.argsort(-probabilities, axis=1)[:, :k]
    return float((top == labels[:, None]).any(axis=1).mean())


@dataclass
class FitResult:
    ranker: DeveloperRanker
    history: list[dict[str, float]]
    seconds: float


def fit(
    train_texts: list[str],
    train_labels: list[int],
    valid_texts: list[str],
    valid_labels: list[int],
    developers: list[str],
    epochs: int,
    seed: int,
    vocabulary: Vocabulary | None = None,
) -> FitResult:
    """Train a CNN-LSTM with early stopping on validation top-3 (patience 2)."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    vocabulary = vocabulary or Vocabulary.build(train_texts)
    x_train = torch.from_numpy(vocabulary.encode(train_texts))
    y_train = torch.tensor(train_labels)
    y_valid = np.array(valid_labels)

    model = CNNLSTM(ModelConfig(vocab_size=len(vocabulary), num_classes=len(developers)))
    optimiser = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-4)
    loss_fn = nn.CrossEntropyLoss()
    ranker = DeveloperRanker(model, vocabulary, developers)
    best_score, best_state, history = -1.0, None, []
    patience, waited = 2, 0
    started = time.perf_counter()
    for epoch in range(1, epochs + 1):
        model.train()
        permutation = torch.randperm(len(x_train))
        total = 0.0
        for start in range(0, len(x_train), 128):
            batch = permutation[start : start + 128]
            optimiser.zero_grad()
            loss = loss_fn(model(x_train[batch]), y_train[batch])
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimiser.step()
            total += loss.item() * len(batch)
        model.eval()
        probabilities = ranker.probabilities(valid_texts)
        top3 = top_k_accuracy(probabilities, y_valid, 3)
        history.append(
            {
                "epoch": epoch,
                "train_loss": round(total / len(x_train), 4),
                "valid_top1": round(top_k_accuracy(probabilities, y_valid, 1), 4),
                "valid_top3": round(top3, 4),
            }
        )
        print(f"  epoch {epoch}: {history[-1]}", flush=True)
        if top3 > best_score:
            best_score, waited = top3, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            waited += 1
            if waited >= patience:
                break
    assert best_state is not None  # noqa: S101 (at least one epoch ran)
    model.load_state_dict(best_state)
    return FitResult(
        DeveloperRanker(model, vocabulary, developers), history, time.perf_counter() - started
    )


def train(ecosystem: str, epochs: int, sample: int | None, seed: int) -> dict[str, object]:
    torch.manual_seed(seed)
    np.random.seed(seed)
    dataset = assignment_data.load(ecosystem, sample=sample)
    index = {d: i for i, d in enumerate(dataset.developers)}
    train_texts = assignment_data.model_text(dataset.train)
    vocabulary = Vocabulary.build(train_texts)
    result = fit(
        train_texts,
        [index[d] for d in dataset.train["fixer"]],
        assignment_data.model_text(dataset.validation),
        [index[d] for d in dataset.validation["fixer"]],
        dataset.developers,
        epochs,
        seed,
        vocabulary,
    )
    model, history = result.ranker.model, result.history
    out = ARTIFACTS / "assignment" / ecosystem
    result.ranker.save(out)
    summary = {
        "ecosystem": ecosystem,
        "developers": len(dataset.developers),
        "min_fixes_per_developer": assignment_data.MIN_FIXES,
        "train": len(dataset.train),
        "validation": len(dataset.validation),
        "sample_most_recent": sample,
        "vocabulary": len(vocabulary),
        "epochs_run": len(history),
        "history": history,
        "training_seconds": round(result.seconds, 1),
        "parameters": sum(p.numel() for p in model.parameters()),
    }
    (out / "training.json").write_text(json.dumps(summary, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ecosystem", default="eclipse", choices=["eclipse", "mozilla"])
    parser.add_argument("--epochs", type=int, default=10)
    parser.add_argument("--sample", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    torch.set_num_threads(max(1, torch.get_num_threads()))
    summary = train(args.ecosystem, args.epochs, args.sample, args.seed)
    print(
        f"[assignment/{args.ecosystem}] {summary['developers']} developers, "
        f"{summary['train']} train, {summary['training_seconds']}s"
    )


if __name__ == "__main__":
    main()
