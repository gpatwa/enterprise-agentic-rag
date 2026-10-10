"""Append-only triage records for structured feedback.

Revision ID: 0006_feedback_triage
Revises: 0005_analytics_feedback
"""

import sqlalchemy as sa
from alembic import op

revision = "0006_feedback_triage"
down_revision = "0005_analytics_feedback"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_feedback_triage",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("triage_id", sa.String(length=255), nullable=False),
        sa.Column("feedback_id", sa.String(length=255), nullable=False),
        sa.Column("rules_version", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("rule_id", sa.String(length=64), nullable=False),
        sa.Column("decision_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "triage_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "feedback_id"], ["analytics_feedback.tenant_id", "analytics_feedback.feedback_id"]
        ),
        sa.UniqueConstraint("tenant_id", "feedback_id", "rules_version", name="uq_triage_per_rules_version"),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"""CREATE TRIGGER trg_feedback_triage_no_{action.lower()}
                BEFORE {action} ON analytics_feedback_triage
                BEGIN SELECT RAISE(ABORT, 'triage records are append-only'); END"""
            )
    elif bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_feedback_triage_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'triage records are append-only'; END; $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_feedback_triage_no_mutation
            BEFORE UPDATE OR DELETE ON analytics_feedback_triage
            FOR EACH ROW EXECUTE FUNCTION reject_feedback_triage_mutation()"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_feedback_triage_no_mutation ON analytics_feedback_triage")
        op.execute("DROP FUNCTION IF EXISTS reject_feedback_triage_mutation()")
    op.drop_table("analytics_feedback_triage")
