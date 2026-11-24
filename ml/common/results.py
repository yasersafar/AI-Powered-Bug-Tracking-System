"""Helpers to write evaluation outputs into docs/results/ with provenance."""

import json
import platform
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ml.common.paths import RESULTS


def provenance() -> dict[str, str]:
    import sklearn
    import torch

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "python": platform.python_version(),
        "machine": f"{platform.system()} {platform.machine()}",
        "scikit_learn": sklearn.__version__,
        "torch": torch.__version__,
    }


def write_json(name: str, payload: dict[str, Any]) -> Path:
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps({"provenance": provenance(), **payload}, indent=2, default=str))
    return path
