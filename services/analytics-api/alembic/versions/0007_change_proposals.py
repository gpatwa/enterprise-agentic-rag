"""Append-only change proposals and their supporting triage links.

Revision ID: 0007_change_proposals
Revises: 0006_feedback_triage
"""

import sqlalchemy as sa
from alembic import op

revision = "0007_change_proposals"
down_revision = "0006_feedback_triage"
branch_labels = None
depends_on = None

_TABLES = ("analytics_change_proposals", "analytics_proposal_support")


def upgrade() -> None:
    op.create_table(
        "analytics_change_proposals",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("proposal_id", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("operation", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.String(length=255), nullable=False),
        sa.Column("base_contract", sa.String(length=512), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "proposal_id"),
    )
    op.create_table(
        "analytics_proposal_support",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("proposal_id", sa.String(length=255), nullable=False),
        sa.Column("triage_id", sa.String(length=255), nullable=False),
        sa.Column("feedback_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "proposal_id", "triage_id"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "proposal_id"],
            ["analytics_change_proposals.tenant_id", "analytics_change_proposals.proposal_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "triage_id"],
            ["analytics_feedback_triage.tenant_id", "analytics_feedback_triage.triage_id"],
        ),
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
