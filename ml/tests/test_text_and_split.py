import pandas as pd

from ml.common.split import time_split
from ml.common.text import clean_text, report_text, tokenize


def test_clean_text_removes_noise() -> None:
    raw = "Crash (1GI5UXW) at 0xDEADBEEF see https://bugs.example.org/123;  id 1234567"
    assert clean_text(raw) == "Crash at hexaddr see url id num"


def test_report_text_puts_title_first_and_truncates() -> None:
    assert report_text("Title", "body " * 2000, max_chars=20) == "Title. body body bod"
    assert report_text(None, None) == "."


def test_tokenize_lowercases_and_drops_stopwords() -> None:
    assert tokenize("The NullPointerException in the Editor_View") == [
        "nullpointerexception",
        "editor_view",
    ]


def test_time_split_is_chronological() -> None:
    frame = pd.DataFrame(
        {"bug_id": range(10), "created": pd.date_range("2020-01-01", periods=10)[::-1]}
    )
    train, test = time_split(frame, test_fraction=0.3)
    assert len(train) == 7 and len(test) == 3
    assert train["created"].max() < test["created"].min()
