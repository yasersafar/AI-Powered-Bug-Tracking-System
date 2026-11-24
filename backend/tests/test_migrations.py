"""Migrated schema vs models where `alembic check` cannot see: CHECK constraints."""

from sqlalchemy import CheckConstraint, text
from sqlalchemy.orm import Session

import app.models  # noqa: F401
from app.core.database import Base


def test_check_constraints_match_models(db: Session) -> None:
    expected = {
        str(constraint.name)
        for table in Base.metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    actual = set(
        db.scalars(
            text(
                "SELECT c.conname FROM pg_constraint c "
                "JOIN pg_class t ON t.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = t.relnamespace "
                "WHERE c.contype = 'c' AND n.nspname = 'public'"
            )
        )
    )
    assert actual == expected
