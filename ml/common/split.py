"""Time-based train/test split: train on older reports, test on newer ones (no leakage)."""

import pandas as pd


def time_split(
    frame: pd.DataFrame, test_fraction: float = 0.2, time_column: str = "created"
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = frame.sort_values([time_column, "bug_id"]).reset_index(drop=True)
    cut = round(len(ordered) * (1 - test_fraction))
    return ordered.iloc[:cut].reset_index(drop=True), ordered.iloc[cut:].reset_index(drop=True)


def describe_split(
    train: pd.DataFrame, test: pd.DataFrame, time_column: str = "created"
) -> dict[str, object]:
    return {
        "train_size": len(train),
        "test_size": len(test),
        "train_period": [
            str(train[time_column].min().date()),
            str(train[time_column].max().date()),
        ],
        "test_period": [str(test[time_column].min().date()), str(test[time_column].max().date())],
    }
