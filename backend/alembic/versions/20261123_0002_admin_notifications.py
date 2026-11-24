"""Developer profiles, assignment/resolution history, runtime settings, notifications.

Revision ID: 0002_admin_notifications
Revises: 0001_core_schema
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_admin_notifications"
down_revision: str | None = "0001_core_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXPERIENCE = postgresql.ENUM("Junior", "Mid", "Senior", name="experience_level", create_type=False)
AVAILABILITY = postgresql.ENUM(
    "Available", "Limited", "Unavailable", name="availability", create_type=False
)
ASSIGNMENT_END = postgresql.ENUM("reassigned", "closed", name="assignment_end", create_type=False)
NOTIFICATION_KIND = postgresql.ENUM(
    "assigned", "status_changed", "critical_bug", name="notification_kind", create_type=False
)
DELIVERY = postgresql.ENUM(
    "pending", "sent", "failed", "skipped", name="delivery_status", create_type=False
)
NEW_ENUMS = (EXPERIENCE, AVAILABILITY, ASSIGNMENT_END, NOTIFICATION_KIND, DELIVERY)
SEVERITY = postgresql.ENUM(name="severity", create_type=False)  # created in 0001


def _now(name: str) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(name, sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)


def _fk(column: str, target: str, name: str, ondelete: str, nullable: bool = False) -> sa.Column:  # type: ignore[type-arg]
    return sa.Column(
        column, sa.Integer(), sa.ForeignKey(target, name=name, ondelete=ondelete), nullable=nullable
    )


def upgrade() -> None:
    bind = op.get_bind()
    for enum in NEW_ENUMS:
        enum.create(bind, checkfirst=True)

    op.create_table(
        "developer_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        _fk("user_id", "user.id", "fk_developer_profile_user_id_user", "CASCADE"),
        sa.Column("languages", postgresql.ARRAY(sa.String(40)), server_default="{}", nullable=False),
        sa.Column("experience_level", EXPERIENCE, nullable=False),
        sa.Column("availability", AVAILABILITY, nullable=False),
        sa.Column("max_workload", sa.Integer(), server_default="5", nullable=False),
        sa.Column("active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("resolved_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_cold_start", sa.Boolean(), server_default="true", nullable=False),
        _now("created_at"),
        _now("updated_at"),
        sa.CheckConstraint("max_workload >= 1", name=op.f("ck_developer_profile_max_workload_positive")),
        sa.CheckConstraint(
            "resolved_count >= 0", name=op.f("ck_developer_profile_resolved_count_non_negative")
        ),
        sa.UniqueConstraint("user_id", name="uq_developer_profile_user_id"),
    )

    for table, column, length, uq in (
        ("profile_skill", "skill", 60, "uq_profile_skill"),
        ("profile_component", "component", 80, "uq_profile_component"),
    ):
        op.create_table(
            table,
            sa.Column("id", sa.Integer(), primary_key=True),
            _fk(
                "profile_id",
                "developer_profile.id",
                f"fk_{table}_profile_id_developer_profile",
                "CASCADE",
            ),
            sa.Column(column, sa.String(length), nullable=False),
            sa.UniqueConstraint("profile_id", column, name=uq),
        )
        op.create_index(f"ix_{table}_profile_id", table, ["profile_id"])

    op.create_table(
        "bug_assignment",
        sa.Column("id", sa.Integer(), primary_key=True),
        _fk("bug_id", "bug.id", "fk_bug_assignment_bug_id_bug", "CASCADE"),
        _fk("developer_id", "user.id", "fk_bug_assignment_developer_id_user", "CASCADE"),
        _fk("assigned_by_id", "user.id", "fk_bug_assignment_assigned_by_id_user", "SET NULL", True),
        _now("assigned_at"),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", ASSIGNMENT_END, nullable=True),
    )
    op.create_index("ix_bug_assignment_bug_id", "bug_assignment", ["bug_id"])
    op.create_index("ix_bug_assignment_developer", "bug_assignment", ["developer_id", "ended_reason"])
    op.create_index(
        "uq_bug_assignment_one_open",
        "bug_assignment",
        ["bug_id"],
        unique=True,
        postgresql_where=sa.text("ended_at IS NULL"),
    )

    op.create_table(
        "resolution_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        _fk("bug_id", "bug.id", "fk_resolution_history_bug_id_bug", "CASCADE"),
        _fk("developer_id", "user.id", "fk_resolution_history_developer_id_user", "CASCADE"),
        _fk("project_id", "project.id", "fk_resolution_history_project_id_project", "CASCADE"),
        sa.Column("severity", SEVERITY, nullable=False),
        sa.Column(
            "components", postgresql.ARRAY(sa.String(80)), server_default="{}", nullable=False
        ),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution_hours", sa.Float(), nullable=False),
        sa.Column("reopened", sa.Boolean(), server_default="false", nullable=False),
    )
    op.create_index("ix_resolution_history_bug_id", "resolution_history", ["bug_id"])
    op.create_index(
        "ix_resolution_history_developer", "resolution_history", ["developer_id", "reopened"]
    )

    op.create_table(
        "system_setting",
        sa.Column("key", sa.String(60), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        _fk("updated_by_id", "user.id", "fk_system_setting_updated_by_id_user", "SET NULL", True),
        _now("updated_at"),
    )

    op.create_table(
        "notification",
        sa.Column("id", sa.Integer(), primary_key=True),
        _fk("user_id", "user.id", "fk_notification_user_id_user", "CASCADE"),
        _fk("bug_id", "bug.id", "fk_notification_bug_id_bug", "CASCADE", True),
        sa.Column("kind", NOTIFICATION_KIND, nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("email_status", DELIVERY, nullable=False),
        sa.Column("push_status", DELIVERY, nullable=False),
        _now("created_at"),
    )
    op.create_index(
        "ix_notification_user_unread", "notification", ["user_id", "is_read", "created_at"]
    )

    # audit_log gains a fourth target: developer profiles (FR-20).
    op.add_column(
        "audit_log",
        _fk(
            "profile_id",
            "developer_profile.id",
            "fk_audit_log_profile_id_developer_profile",
            "CASCADE",
            True,
        ),
    )
    op.create_index("ix_audit_log_profile_id", "audit_log", ["profile_id"])
    op.drop_constraint(op.f("ck_audit_log_exactly_one_target"), "audit_log", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_log_exactly_one_target"),
        "audit_log",
        "num_nonnulls(bug_id, project_id, target_user_id, profile_id) = 1",
    )


def downgrade() -> None:
    op.execute("DELETE FROM audit_log WHERE profile_id IS NOT NULL")
    op.drop_constraint(op.f("ck_audit_log_exactly_one_target"), "audit_log", type_="check")
    op.create_check_constraint(
        op.f("ck_audit_log_exactly_one_target"),
        "audit_log",
        "num_nonnulls(bug_id, project_id, target_user_id) = 1",
    )
    op.drop_index("ix_audit_log_profile_id", table_name="audit_log")
    op.drop_column("audit_log", "profile_id")
    for table in (
        "notification",
        "system_setting",
        "resolution_history",
        "bug_assignment",
        "profile_component",
        "profile_skill",
        "developer_profile",
    ):
        op.drop_table(table)
    bind = op.get_bind()
    for enum in reversed(NEW_ENUMS):
        enum.drop(bind, checkfirst=True)
