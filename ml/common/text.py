"""Text cleaning shared by training and inference (the same function must be used by both)."""

import re

_LEGACY_ID = re.compile(r"\(\s*1[A-Z0-9]{6}\s*\)")  # old Eclipse ids like (1GI5UXW)
_URL = re.compile(r"https?://\S+")
_HEX = re.compile(r"\b0x[0-9a-fA-F]+\b")
_LONG_NUMBER = re.compile(r"\b\d{5,}\b")
_WHITESPACE = re.compile(r"\s+")
_TOKEN = re.compile(r"[a-z][a-z0-9_]+|\d+")
STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "for",
        "from",
        "has",
        "have",
        "i",
        "if",
        "in",
        "into",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "when",
        "which",
        "while",
        "will",
        "with",
        "you",
        "your",
        "we",
        "they",
        "he",
        "she",
        "not",
        "no",
        "can",
        "could",
        "should",
        "would",
        "do",
        "does",
        "did",
        "so",
        "than",
        "then",
        "too",
        "very",
        "just",
        "also",
    ]
)


def clean_text(text: str | None, max_chars: int = 4000) -> str:
    """Normalise a bug report field: drop URLs, hex addresses, legacy ids, extra whitespace."""
    if not text:
        return ""
    value = _LEGACY_ID.sub(" ", text)
    value = _URL.sub(" url ", value)
    value = _HEX.sub(" hexaddr ", value)
    value = _LONG_NUMBER.sub(" num ", value)
    value = value.replace(";", " ")  # bugrepo stores newlines as ';'
    return _WHITESPACE.sub(" ", value).strip()[:max_chars]


def report_text(title: str | None, description: str | None, max_chars: int = 4000) -> str:
    """Title first (it is the most informative part), then the description."""
    return clean_text(f"{title or ''}. {description or ''}", max_chars)


def tokenize(text: str) -> list[str]:
    """Lower-case word tokens without stop words (used by BM25 and the CNN-LSTM vocabulary)."""
    return [t for t in _TOKEN.findall(text.lower()) if t not in STOPWORDS]
