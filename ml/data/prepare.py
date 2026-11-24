"""Join the two public datasets into analysis-ready tables (ml/data/processed/*.parquet).

Inputs (from `ml/data/download.sh`):
  * logpai/bugrepo CSVs - title, description, component, duplicate link, created time
  * Lamkanfi et al. MSR 2013 JSON - severity and assignee histories, product, resolution

Output per ecosystem (eclipse, mozilla): one row per bug present in both sources.
Developer e-mail addresses are replaced by salted SHA-256 pseudonyms (`dev_<10 hex>`), and
shared inbox / placeholder accounts are mapped to None.

    python -m ml.data.prepare
"""

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pandas as pd

from ml.common.paths import PROCESSED, RAW
from ml.common.text import report_text

SOURCES = {
    "eclipse": ["unzipped/eclipse_platform.csv", "eclipse_jdt.csv"],
    "mozilla": [
        "unzipped/mozilla_core.csv",
        "unzipped/mozilla_firefox.csv",
        "mozilla_thunderbird.csv",
    ],
}
# Bugzilla severity -> our four levels (enhancement = feature request: dropped).
SEVERITY_MAP = {
    "blocker": "Critical",
    "critical": "Critical",
    "major": "High",
    "normal": "Medium",
    "minor": "Low",
    "trivial": "Low",
}
GENERIC_ACCOUNT = re.compile(
    r"(^|[-._])inbox@|^nobody@|^general@|^webmaster@|-triaged@|^issues@|@bugs$|^<none>$", re.I
)
PSEUDONYM_SALT = "capstone-ii-bug-triage"


def pseudonym(email: str | None) -> str | None:
    if not email or GENERIC_ACCOUNT.search(email):
        return None
    digest = hashlib.sha256(f"{PSEUDONYM_SALT}:{email.lower()}".encode()).hexdigest()
    return f"dev_{digest[:10]}"


def _history(path: Path, key: str) -> dict[str, Any]:
    with path.open() as handle:
        data: dict[str, Any] = json.load(handle)[key]
    return data


def build(ecosystem: str) -> pd.DataFrame:
    frames = [
        pd.read_csv(
            RAW / "bugrepo" / name,
            usecols=[
                "Issue_id",
                "Component",
                "Duplicated_issue",
                "Title",
                "Description",
                "Created_time",
            ],
            dtype={"Issue_id": str},
        )
        for name in SOURCES[ecosystem]
    ]
    text = pd.concat(frames).drop_duplicates("Issue_id").set_index("Issue_id")

    msr = RAW / "msr2013" / ecosystem
    reports = _history(msr / "reports.json", "reports")
    severity = _history(msr / "severity.json", "severity")
    assigned = _history(msr / "assigned_to.json", "assigned_to")
    product = _history(msr / "product.json", "product")
    component = _history(msr / "component.json", "component")

    rows = []
    for bug_id, row in text.iterrows():
        bug_id = str(bug_id)
        if bug_id not in reports or bug_id not in severity:
            continue
        report = reports[bug_id]
        sev_history = severity[bug_id]
        owners = [pseudonym(h["what"]) for h in assigned.get(bug_id, [])]
        rows.append(
            {
                "bug_id": int(bug_id),
                "product": (product.get(bug_id) or [{"what": None}])[-1]["what"],
                "component": (component.get(bug_id) or [{"what": row["Component"]}])[-1]["what"],
                "title": row["Title"] if isinstance(row["Title"], str) else "",
                "description": row["Description"] if isinstance(row["Description"], str) else "",
                "text": report_text(row["Title"], row["Description"]),
                "created": pd.Timestamp(report["opening"], unit="s", tz="UTC"),
                "resolution": report.get("current_resolution") or "",
                "severity_raw_initial": sev_history[0]["what"],
                "severity_raw_final": sev_history[-1]["what"],
                "severity": SEVERITY_MAP.get(sev_history[-1]["what"]),
                "fixer": owners[-1] if owners else None,
                "assignee_changes": max(0, len(owners) - 1),
                "duplicate_of": (
                    int(row["Duplicated_issue"]) if pd.notna(row["Duplicated_issue"]) else None
                ),
            }
        )
    frame = pd.DataFrame(rows).sort_values(["created", "bug_id"]).reset_index(drop=True)
    frame["duplicate_of"] = frame["duplicate_of"].astype("Int64")
    return frame


def main() -> None:
    PROCESSED.mkdir(parents=True, exist_ok=True)
    for ecosystem in SOURCES:
        frame = build(ecosystem)
        out = PROCESSED / f"{ecosystem}.parquet"
        frame.to_parquet(out, index=False)
        print(f"{ecosystem}: {len(frame):,} bugs -> {out.relative_to(PROCESSED.parent.parent)}")


if __name__ == "__main__":
    main()
