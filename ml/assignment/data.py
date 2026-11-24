"""Assignment dataset: FIXED bugs with a personal (non-inbox) final assignee, split by time.

Developer classes = developers with at least MIN_FIXES fixes in the *training* period
(threshold chosen before evaluation; rarer developers cannot be learned). Test bugs whose fixer
is not a class are reported as "not covered" and excluded from accuracy.
"""

from dataclasses import dataclass

import pandas as pd

from ml.common.paths import PROCESSED
from ml.common.split import time_split

MIN_FIXES = 50


@dataclass
class AssignmentData:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    developers: list[str]
    test_total: int  # before removing uncovered fixers


def model_text(frame: pd.DataFrame) -> list[str]:
    """Report text plus the component as an extra token (the component is known at triage)."""
    return [
        f"component_{str(c).lower().replace(' ', '_')} {t}"
        for c, t in zip(frame["component"], frame["text"], strict=True)
    ]


def load(ecosystem: str, min_fixes: int = MIN_FIXES, sample: int | None = None) -> AssignmentData:
    frame = pd.read_parquet(
        PROCESSED / f"{ecosystem}.parquet",
        columns=[
            "bug_id",
            "created",
            "text",
            "component",
            "resolution",
            "fixer",
            "assignee_changes",
        ],
    )
    frame = frame[
        (frame["resolution"] == "FIXED") & frame["fixer"].notna() & (frame["text"].str.len() > 0)
    ]
    if sample is not None and len(frame) > sample:
        frame = frame.sort_values("created").iloc[-sample:]  # most recent reports
    train_full, test = time_split(frame, test_fraction=0.2)
    counts = train_full["fixer"].value_counts()
    developers = sorted(counts[counts >= min_fixes].index)
    keep = set(developers)
    train_full = train_full[train_full["fixer"].isin(keep)].reset_index(drop=True)
    cut = int(len(train_full) * 0.9)  # newest 10% of training period = validation (early stop)
    test_total = len(test)
    test = test[test["fixer"].isin(keep)].reset_index(drop=True)
    return AssignmentData(
        train=train_full.iloc[:cut].reset_index(drop=True),
        validation=train_full.iloc[cut:].reset_index(drop=True),
        test=test,
        developers=developers,
        test_total=test_total,
    )
