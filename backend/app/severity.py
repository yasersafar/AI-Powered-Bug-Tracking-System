"""Severity classification: the bridge between the API and the ML model."""

SEVERITY_LABELS = ("Low", "Medium", "High", "Critical")

# Saved when the AI service is down or fails (NFR-10).
UNCLASSIFIED = "Unclassified"


def classify_severity(title: str, description: str) -> str:
    """Return one of SEVERITY_LABELS, or UNCLASSIFIED.

    Skeleton only: it always returns UNCLASSIFIED for now.
    """
    # TODO(#12, Mj-Raid): load the trained TF-IDF + voting model (saved with joblib
    #   under ml/severity/) and return its predicted label for title + description.
    # TODO(#13, MohammedAfSaleh): if the model is missing or raises an error, log it
    #   and return UNCLASSIFIED so the bug is still saved.
    return UNCLASSIFIED
