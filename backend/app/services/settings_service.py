"""Runtime-configurable thresholds (NFR-14).

Values live in the `system_setting` table and are read on every use, so an Administrator's
change takes effect on the next request without a redeploy. Unset keys use the defaults below.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.models import SystemSetting, User


@dataclass(frozen=True)
class SettingSpec:
    key: str
    kind: type[int] | type[float]
    default: float
    minimum: float
    maximum: float
    description: str
    unit: str = ""


SPECS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        SettingSpec(
            "duplicate_min_score",
            float,
            0.5,
            0.0,
            1.0,
            "Lowest similarity for a report to be shown as a possible duplicate (FR-10).",
        ),
        SettingSpec(
            "duplicate_likely_threshold",
            float,
            0.8,
            0.0,
            1.0,
            "Similarity at which a report counts as a likely duplicate; the recommender then "
            "boosts developers who fixed the original bug.",
        ),
        SettingSpec("duplicate_top_k", int, 3, 1, 10, "Number of duplicate candidates returned."),
        SettingSpec(
            "cold_start_threshold",
            int,
            10,
            1,
            1000,
            "N: resolved bugs after which a developer is no longer cold-start (FR-22). "
            "alpha = min(1, resolved_count / N).",
            "bugs",
        ),
        SettingSpec(
            "exploration_rate",
            float,
            0.1,
            0.0,
            1.0,
            "Probability (epsilon) that slot 3 of the recommendations is reserved for the "
            "best-matching cold-start developer (FR-22).",
        ),
        SettingSpec(
            "availability_bonus",
            float,
            0.1,
            0.0,
            1.0,
            "Bonus added to the profile score of developers marked Available.",
        ),
        SettingSpec(
            "ai_enabled",
            int,
            1,
            0,
            1,
            "1 = run the AI triage pipeline; 0 = switch it off (bugs are saved as "
            "Unclassified, NFR-10). Used for the AI-down demo and maintenance.",
        ),
        SettingSpec(
            "duplicate_timeout_ms",
            int,
            1200,
            100,
            10000,
            "Time budget for duplicate detection before it is marked degraded (NFR-02).",
            "ms",
        ),
        SettingSpec(
            "severity_timeout_ms",
            int,
            1200,
            100,
            10000,
            "Time budget for severity classification before it is marked degraded.",
            "ms",
        ),
        SettingSpec(
            "assignment_timeout_ms",
            int,
            2500,
            100,
            10000,
            "Time budget for developer recommendation before it is marked degraded.",
            "ms",
        ),
    )
}


@dataclass
class SettingValue:
    spec: SettingSpec
    value: float
    updated_at: datetime | None
    updated_by: User | None


def _coerce(spec: SettingSpec, raw: Any) -> float:
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        raise ValueError(f"{spec.key} must be a number")
    if spec.kind is int:
        if float(raw) != int(raw):
            raise ValueError(f"{spec.key} must be a whole number")
        value: float = int(raw)
    else:
        value = float(raw)
    if not spec.minimum <= value <= spec.maximum:
        raise ValueError(f"{spec.key} must be between {spec.minimum} and {spec.maximum}")
    return value


def get_value(db: Session, key: str) -> float:
    spec = SPECS[key]
    row = db.get(SystemSetting, key)
    if row is None:
        return spec.default
    try:
        return _coerce(spec, row.value)
    except ValueError:
        return spec.default


def get_values(db: Session) -> dict[str, float]:
    rows = {row.key: row for row in db.scalars(select(SystemSetting))}
    values: dict[str, float] = {}
    for key, spec in SPECS.items():
        row = rows.get(key)
        try:
            values[key] = _coerce(spec, row.value) if row is not None else spec.default
        except ValueError:
            values[key] = spec.default
    return values


def list_settings(db: Session) -> list[SettingValue]:
    rows = {row.key: row for row in db.scalars(select(SystemSetting))}
    values = get_values(db)
    result = []
    for key, spec in SPECS.items():
        row = rows.get(key)
        updated_by = db.get(User, row.updated_by_id) if row and row.updated_by_id else None
        result.append(SettingValue(spec, values[key], row.updated_at if row else None, updated_by))
    return result


def update_settings(db: Session, admin: User, changes: dict[str, Any]) -> dict[str, float]:
    unknown = sorted(set(changes) - set(SPECS))
    if unknown:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown_setting", "Unknown setting", unknown
        )
    errors: dict[str, str] = {}
    coerced: dict[str, float] = {}
    for key, raw in changes.items():
        try:
            coerced[key] = _coerce(SPECS[key], raw)
        except ValueError as exc:
            errors[key] = str(exc)
    merged = {**get_values(db), **coerced}
    if merged["duplicate_likely_threshold"] < merged["duplicate_min_score"]:
        errors["duplicate_likely_threshold"] = "must be >= duplicate_min_score"
    if errors:
        raise AppError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "invalid_setting",
            "Invalid setting value",
            errors,
        )

    for key, value in coerced.items():
        row = db.get(SystemSetting, key)
        if row is None:
            db.add(SystemSetting(key=key, value=value, updated_by_id=admin.id))
        else:
            row.value = value
            row.updated_by_id = admin.id
    db.flush()
    if "cold_start_threshold" in coerced:
        from app.services import developer_activity  # local import: avoids a cycle

        developer_activity.refresh_cold_start_flags(db, int(coerced["cold_start_threshold"]))
    db.commit()
    return get_values(db)
