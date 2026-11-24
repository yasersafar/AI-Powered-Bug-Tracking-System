"""Core schema: users, projects, members, bugs, comments, attachments, audit log.

Revision ID: 0001_core_schema
Revises:
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_core_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

USER_ROLE = postgresql.ENUM(
    "Reporter", "Developer", "ProjectManager", "Administrator", name="user_role", create_type=False
)
PROJECT_ROLE = postgresql.ENUM(
    "Reporter", "Developer", "ProjectManager", name="project_role", create_type=False
)
SEVERITY = postgresql.ENUM(
    "Low", "Medium", "High", "Critical", "Unclassified", name="severity", create_type=False
)
BUG_STATUS = postgresql.ENUM(
    "Open", "InProgress", "Resolved", "Verified", "Closed", name="bug_status", create_type=False
)
AI_STATUS = postgresql.ENUM("ok", "degraded", name="ai_status", create_type=False)
CLOSE_REASON = postgresql.ENUM(
    "fixed", "invalid", "duplicate", name="close_reason", create_type=False
)
ENUMS = (USER_ROLE, PROJECT_ROLE, SEVERITY, BUG_STATUS, AI_STATUS, CLOSE_REASON)

SEARCH_VECTOR_SQL = (
    "setweight(to_tsvector('english', coalesce(title, '')), 'A') || "
    "setweight(to_tsvector('english', coalesce(description, '')), 'B')"
)


def _ts(name: str, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    if nullable:
        return sa.Column(name, sa.DateTime(timezone=True), nullable=True)
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def upgrade() -> None:
    bind = op.get_bind()
    for enum in ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(254), nullable=False),
        sa.Column("full_name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(100), nullable=False),
        sa.Column("role", USER_ROLE, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("email_notifications", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("push_notifications", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("ntfy_topic", sa.String(64), nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("ntfy_topic", name="uq_user_ntfy_topic"),
    )
    op.create_index("ix_user_email", "user", ["email"], unique=True)

    op.create_table(
        "project",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("is_archived", sa.Boolean(), server_default="false", nullable=False),
        _ts("archived_at", nullable=True),
        sa.Column(
            "created_by_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_project_created_by_id_user", ondelete="SET NULL"),
            nullable=True,
        ),
        _ts("created_at"),
        sa.UniqueConstraint("name", name="uq_project_name"),
    )

    op.create_table(
        "project_member",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey(
                "project.id", name="fk_project_member_project_id_project", ondelete="CASCADE"
            ),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_project_member_user_id_user", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", PROJECT_ROLE, nullable=False),
        _ts("joined_at"),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member_user"),
    )
    op.create_index("ix_project_member_project_id", "project_member", ["project_id"])
    op.create_index("ix_project_member_user_id", "project_member", ["user_id"])

    op.create_table(
        "bug",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", name="fk_bug_project_id_project", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reporter_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_bug_reporter_id_user", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "assignee_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_bug_assignee_id_user", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("steps_to_reproduce", sa.Text(), nullable=False),
        sa.Column("environment", sa.String(500), nullable=False),
        sa.Column(
            "components", postgresql.ARRAY(sa.String(80)), server_default="{}", nullable=False
        ),
        sa.Column("status", BUG_STATUS, nullable=False),
        sa.Column("severity", SEVERITY, nullable=False),
        sa.Column("close_reason", CLOSE_REASON, nullable=True),
        sa.Column(
            "duplicate_of_id",
            sa.Integer(),
            sa.ForeignKey("bug.id", name="fk_bug_duplicate_of_id_bug", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("predicted_severity", SEVERITY, nullable=True),
        sa.Column("severity_confidence", sa.Float(), nullable=True),
        sa.Column("severity_overridden", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "duplicate_candidates", postgresql.JSONB(), server_default="[]", nullable=False
        ),
        sa.Column(
            "recommended_developers", postgresql.JSONB(), server_default="[]", nullable=False
        ),
        sa.Column("ai_status", AI_STATUS, nullable=False),
        _ts("created_at"),
        _ts("updated_at"),
        _ts("resolved_at", nullable=True),
        _ts("closed_at", nullable=True),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed(SEARCH_VECTOR_SQL, persisted=True),
            nullable=True,
        ),
        sa.CheckConstraint(
            "duplicate_of_id IS NULL OR duplicate_of_id <> id", name=op.f("ck_bug_not_self_duplicate")
        ),
        sa.CheckConstraint(
            "severity_confidence IS NULL OR severity_confidence BETWEEN 0 AND 1",
            name=op.f("ck_bug_confidence_range"),
        ),
    )
    # FR-07: B-tree indexes on the filter columns + GIN on the full-text vector.
    op.create_index("ix_bug_project_id", "bug", ["project_id"])
    op.create_index("ix_bug_assignee_id", "bug", ["assignee_id"])
    op.create_index("ix_bug_status", "bug", ["status"])
    op.create_index("ix_bug_severity", "bug", ["severity"])
    op.create_index("ix_bug_created_at", "bug", ["created_at"])
    op.create_index("ix_bug_search_vector", "bug", ["search_vector"], postgresql_using="gin")

    op.create_table(
        "comment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bug_id",
            sa.Integer(),
            sa.ForeignKey("bug.id", name="fk_comment_bug_id_bug", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "author_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_comment_author_id_user", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("body", sa.Text(), nullable=False),
        _ts("created_at"),
    )
    op.create_index("ix_comment_bug_created", "comment", ["bug_id", "created_at"])

    op.create_table(
        "attachment",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "bug_id",
            sa.Integer(),
            sa.ForeignKey("bug.id", name="fk_attachment_bug_id_bug", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "uploader_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_attachment_uploader_id_user", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("storage_key", sa.String(64), nullable=False),
        sa.Column("content_type", sa.String(100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        _ts("created_at"),
        sa.UniqueConstraint("storage_key", name="uq_attachment_storage_key"),
    )
    op.create_index("ix_attachment_bug_id", "attachment", ["bug_id"])

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "actor_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_audit_log_actor_id_user", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("field", sa.String(60), nullable=True),
        sa.Column("old_value", sa.Text(), nullable=True),
        sa.Column("new_value", sa.Text(), nullable=True),
        sa.Column(
            "bug_id",
            sa.Integer(),
            sa.ForeignKey("bug.id", name="fk_audit_log_bug_id_bug", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            sa.Integer(),
            sa.ForeignKey("project.id", name="fk_audit_log_project_id_project", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "target_user_id",
            sa.Integer(),
            sa.ForeignKey("user.id", name="fk_audit_log_target_user_id_user", ondelete="CASCADE"),
            nullable=True,
        ),
        _ts("created_at"),
        sa.CheckConstraint(
            "num_nonnulls(bug_id, project_id, target_user_id) = 1",
            name=op.f("ck_audit_log_exactly_one_target"),
        ),
    )
    op.create_index("ix_audit_log_bug_created", "audit_log", ["bug_id", "created_at"])
    op.create_index("ix_audit_log_project_created", "audit_log", ["project_id", "created_at"])
    op.create_index("ix_audit_log_target_user_id", "audit_log", ["target_user_id"])


def downgrade() -> None:
    for table in ("audit_log", "attachment", "comment", "bug", "project_member", "project", "user"):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in reversed(ENUMS):
        enum.drop(bind, checkfirst=True)
