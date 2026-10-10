"""Persist identity-bound governed review decisions.

Revision ID: 0003_durable_analytics_reviews
Revises: 0002_agent_control_store
"""

import sqlalchemy as sa
from alembic import op

revision = "0003_durable_analytics_reviews"
down_revision = "0002_agent_control_store"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_run_reviews",
        sa.Column("review_id", sa.String(length=255), primary_key=True),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("plan_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("resolved_by", sa.String(length=255), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.String(length=2000), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'approved', 'rejected', 'expired', 'superseded')", name="ck_run_reviews_state"
        ),
        sa.CheckConstraint("revision >= 1", name="ck_run_reviews_revision"),
    )
    op.create_index("ix_run_reviews_scope_state", "analytics_run_reviews", ["tenant_id", "state", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_run_reviews_scope_state", table_name="analytics_run_reviews")
    op.drop_table("analytics_run_reviews")
