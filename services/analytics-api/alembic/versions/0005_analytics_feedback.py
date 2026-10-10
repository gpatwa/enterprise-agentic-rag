"""Append-only structured feedback on terminal analytics runs.

Revision ID: 0005_analytics_feedback
Revises: 0004_evidence_envelopes
"""

import sqlalchemy as sa
from alembic import op

revision = "0005_analytics_feedback"
down_revision = "0004_evidence_envelopes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_feedback",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("feedback_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("submitted_by", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("submission_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("verdict", sa.String(length=32), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "feedback_id"),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
        ),
        sa.UniqueConstraint("tenant_id", "run_id", "submitted_by", "idempotency_key", name="uq_feedback_idempotency"),
    )
    op.create_index("ix_feedback_run", "analytics_feedback", ["tenant_id", "run_id"])
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"""CREATE TRIGGER trg_analytics_feedback_no_{action.lower()}
                BEFORE {action} ON analytics_feedback
                BEGIN SELECT RAISE(ABORT, 'feedback is append-only'); END"""
            )
    elif bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_feedback_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'feedback is append-only'; END; $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_analytics_feedback_no_mutation
            BEFORE UPDATE OR DELETE ON analytics_feedback
            FOR EACH ROW EXECUTE FUNCTION reject_feedback_mutation()"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_analytics_feedback_no_mutation ON analytics_feedback")
        op.execute("DROP FUNCTION IF EXISTS reject_feedback_mutation()")
    op.drop_index("ix_feedback_run", table_name="analytics_feedback")
    op.drop_table("analytics_feedback")
