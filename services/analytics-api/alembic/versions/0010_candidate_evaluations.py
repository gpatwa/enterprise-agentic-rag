"""Append-only candidate evaluation records.

Revision ID: 0010_candidate_evaluations
Revises: 0009_reviews
"""

import sqlalchemy as sa
from alembic import op

revision = "0010_candidate_evaluations"
down_revision = "0009_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_candidate_evaluations",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("evaluation_id", sa.String(length=255), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("subject_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "evaluation_id"),
        sa.CheckConstraint("verdict IN ('passed', 'failed')", name="ck_candidate_evaluations_verdict"),
    )
    op.create_index(
        "ix_candidate_evaluations_subject",
        "analytics_candidate_evaluations",
        ["tenant_id", "subject_kind", "subject_id", "subject_fingerprint"],
    )
    bind = op.get_bind()
    table = "analytics_candidate_evaluations"
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
    table = "analytics_candidate_evaluations"
    if bind.dialect.name == "postgresql":
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_mutation ON {table}")
        op.execute(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()")
    op.drop_index("ix_candidate_evaluations_subject", table_name=table)
    op.drop_table(table)
