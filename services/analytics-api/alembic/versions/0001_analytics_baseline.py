"""Create the Analytics control-store baseline.

Revision ID: 0001_analytics_baseline
Revises:
Create Date: 2026-08-20 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "0001_analytics_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_query_outcomes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("query_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("user_id", sa.String(length=255), nullable=False),
        sa.Column("dataset", sa.String(length=100), nullable=False),
        sa.Column("outcome", sa.String(length=32), nullable=False),
        sa.Column("contract_version", sa.String(length=16), nullable=False),
        sa.Column("policy_decision_id", sa.String(length=255), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=255), nullable=True),
        sa.Column("response_payload", sa.JSON(), nullable=False),
        sa.Column("evidence_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("query_id"),
    )
    op.create_index(
        "ix_analytics_query_outcomes_tenant_created",
        "analytics_query_outcomes",
        ["tenant_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analytics_query_outcomes_tenant_created", table_name="analytics_query_outcomes")
    op.drop_table("analytics_query_outcomes")
