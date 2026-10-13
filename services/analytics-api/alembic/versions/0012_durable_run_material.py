"""Durable run working material: compiled plans, policy values, and result links (M7-H1).

Plans and policy values were process-local, so a worker process that died after compiling could not be continued by another.
Rows are NOT stored: a result is rebuilt by running the stored plan again while the run is in flight.

Revision ID: 0012_durable_run_material
Revises: 0011_rollouts
"""

import sqlalchemy as sa
from alembic import op

revision = "0012_durable_run_material"
down_revision = "0011_rollouts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    created = sa.Column(
        "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
    )
    op.create_table(
        "analytics_run_plans",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=False),
        created.copy(),
        sa.PrimaryKeyConstraint("tenant_id", "run_id", "reference"),
    )
    op.create_table(
        "analytics_run_policy_values",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("reference", sa.String(length=64), nullable=False),
        sa.Column("policy_values", sa.JSON(), nullable=False),
        created.copy(),
        sa.PrimaryKeyConstraint("tenant_id", "run_id", "reference"),
    )
    op.create_table(
        "analytics_run_result_links",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("result_reference", sa.String(length=64), nullable=False),
        sa.Column("plan_reference", sa.String(length=64), nullable=False),
        created.copy(),
        sa.PrimaryKeyConstraint("tenant_id", "run_id", "result_reference"),
    )


def downgrade() -> None:
    for table in ("analytics_run_result_links", "analytics_run_policy_values", "analytics_run_plans"):
        op.drop_table(table)
