"""durable support jobs for sync-index worker

Revision ID: 0005_support_jobs
Revises: 0004_support_index_records
Create Date: 2026-05-31 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0005_support_jobs"
down_revision = "0004_support_index_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_jobs",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("job_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("providers", sa.JSON(), nullable=True),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("seed_demo", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("current_step", sa.String(length=255), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("canceled_at", sa.DateTime(), nullable=True),
        sa.Column("retry_of_job_id", sa.String(length=64), nullable=True),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_support_jobs_tenant_id", "support_jobs", ["tenant_id"])
    op.create_index("ix_support_jobs_job_type", "support_jobs", ["job_type"])
    op.create_index("ix_support_jobs_status", "support_jobs", ["status"])
    op.create_index("idx_support_job_tenant_status_created", "support_jobs", ["tenant_id", "status", "created_at"])
    op.create_index("idx_support_job_status_locked", "support_jobs", ["status", "locked_at"])
    op.create_index("idx_support_job_type_status", "support_jobs", ["job_type", "status"])


def downgrade() -> None:
    op.drop_index("idx_support_job_type_status", table_name="support_jobs")
    op.drop_index("idx_support_job_status_locked", table_name="support_jobs")
    op.drop_index("idx_support_job_tenant_status_created", table_name="support_jobs")
    op.drop_index("ix_support_jobs_status", table_name="support_jobs")
    op.drop_index("ix_support_jobs_job_type", table_name="support_jobs")
    op.drop_index("ix_support_jobs_tenant_id", table_name="support_jobs")
    op.drop_table("support_jobs")
