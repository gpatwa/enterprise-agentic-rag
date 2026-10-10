"""Append-only rollouts, their events, and the active-version pointer.

Revision ID: 0011_rollouts
Revises: 0010_candidate_evaluations
"""

import sqlalchemy as sa
from alembic import op

revision = "0011_rollouts"
down_revision = "0010_candidate_evaluations"
branch_labels = None
depends_on = None

_TABLES = ("analytics_rollouts", "analytics_rollout_events", "analytics_release_pointer")


def upgrade() -> None:
    op.create_table(
        "analytics_rollouts",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("rollout_id", sa.String(length=255), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("subject_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "rollout_id"),
    )
    op.create_table(
        "analytics_rollout_events",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("rollout_id", sa.String(length=255), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("detail", sa.JSON(), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "rollout_id", "seq"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "rollout_id"], ["analytics_rollouts.tenant_id", "analytics_rollouts.rollout_id"]
        ),
        sa.CheckConstraint("seq > 0", name="ck_rollout_events_seq_positive"),
    )
    op.create_table(
        "analytics_release_pointer",
        sa.Column("prompt_name", sa.String(length=64), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("rollout_id", sa.String(length=255), nullable=True),
        sa.Column("reason", sa.String(length=255), nullable=False),
        sa.Column("set_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("prompt_name", "seq"),
        sa.CheckConstraint("seq > 0", name="ck_release_pointer_seq_positive"),
    )
    bind = op.get_bind()
    for table in _TABLES:
        if bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"""CREATE TRIGGER trg_{table}_no_{action.lower()} BEFORE {action} ON {table}
                    BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"""
                )
        elif bind.dialect.name == "postgresql":
            op.execute(
                f"""CREATE FUNCTION reject_{table}_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$"""
            )
            op.execute(
                f"""CREATE TRIGGER trg_{table}_no_mutation BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_{table}_mutation()"""
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_TABLES):
        if bind.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()")
        op.drop_table(table)
