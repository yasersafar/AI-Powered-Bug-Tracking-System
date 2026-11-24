"""Severity dataset: bugs with a mapped severity (enhancements dropped), split by time."""

import pandas as pd

from ml.common.paths import PROCESSED
from ml.common.split import time_split


def load(ecosystem: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    frame = pd.read_parquet(
        PROCESSED / f"{ecosystem}.parquet", columns=["bug_id", "created", "text", "severity"]
    )
    frame = frame[frame["severity"].notna() & (frame["text"].str.len() > 0)]
    return time_split(frame, test_fraction=0.2)
