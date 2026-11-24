"""Small matplotlib helpers (Agg backend, no display needed)."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def confusion_matrix_png(matrix: np.ndarray, labels: list[str], title: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(5.2, 4.4), dpi=150)
    normalised = matrix / np.maximum(matrix.sum(axis=1, keepdims=True), 1)
    image = ax.imshow(normalised, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(labels)), labels)
    ax.set_yticks(range(len(labels)), labels)
    ax.set_xlabel("Predicted")
    ax.set_ylabel("True")
    ax.set_title(title, fontsize=10)
    for i in range(len(labels)):
        for j in range(len(labels)):
            colour = "white" if normalised[i, j] > 0.5 else "black"
            ax.text(
                j,
                i,
                f"{matrix[i, j]}\n{normalised[i, j]:.0%}",
                ha="center",
                va="center",
                fontsize=7,
                color=colour,
            )
    fig.colorbar(image, ax=ax, fraction=0.046, label="row share")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def bar_png(values: dict[str, float], title: str, ylabel: str, path: Path) -> None:
    fig, ax = plt.subplots(figsize=(6, 3.4), dpi=150)
    ax.bar(list(values), list(values.values()), color="#3b6ea5")
    for i, v in enumerate(values.values()):
        ax.text(i, v, f"{v:.3f}", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel(ylabel)
    ax.set_title(title, fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
