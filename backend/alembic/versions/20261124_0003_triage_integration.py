"""Triage integration: cached report embeddings and per-step AI details on bugs.

Revision ID: 0003_triage_integration
Revises: 0002_admin_notifications
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_triage_integration"
down_revision: str | None = "0002_admin_notifications"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bug_embedding",
        sa.Column(
            "bug_id",
            sa.Integer(),
            sa.ForeignKey("bug.id", name="fk_bug_embedding_bug_id_bug", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("bug_id", name=op.f("pk_bug_embedding")),
    )
    op.add_column(
        "bug",
        sa.Column(
            "ai_details",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("bug", "ai_details")
    op.drop_table("bug_embedding")
