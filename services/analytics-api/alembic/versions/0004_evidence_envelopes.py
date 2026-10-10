"""Append-only, hash-chained evidence envelopes for terminal analytics runs.

Revision ID: 0004_evidence_envelopes
Revises: 0003_durable_analytics_reviews
"""

import sqlalchemy as sa
from alembic import op

revision = "0004_evidence_envelopes"
down_revision = "0003_durable_analytics_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_evidence_envelopes",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("chain_seq", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("terminal_kind", sa.String(length=32), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("previous_hash", sa.String(length=64), nullable=True),
        sa.Column("chain_hash", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "chain_seq"),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
        ),
        sa.UniqueConstraint("tenant_id", "run_id", name="uq_evidence_one_per_run"),
        sa.CheckConstraint("chain_seq > 0", name="ck_evidence_chain_seq_positive"),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"""CREATE TRIGGER trg_evidence_envelopes_no_{action.lower()}
                BEFORE {action} ON analytics_evidence_envelopes
                BEGIN SELECT RAISE(ABORT, 'evidence envelopes are append-only'); END"""
            )
    elif bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_evidence_envelope_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'evidence envelopes are append-only'; END; $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_evidence_envelopes_no_mutation
            BEFORE UPDATE OR DELETE ON analytics_evidence_envelopes
            FOR EACH ROW EXECUTE FUNCTION reject_evidence_envelope_mutation()"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_evidence_envelopes_no_mutation ON analytics_evidence_envelopes")
        op.execute("DROP FUNCTION IF EXISTS reject_evidence_envelope_mutation()")
    op.drop_table("analytics_evidence_envelopes")
