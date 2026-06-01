"""support index records for resolution intelligence

Revision ID: 0004_support_index_records
Revises: 0003_support_data_core
Create Date: 2026-05-31 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0004_support_index_records"
down_revision = "0003_support_data_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_index_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("index_version", sa.String(length=64), nullable=False),
        sa.Column("indexed_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "source_type",
            "source_id",
            name="uq_support_index_record",
        ),
    )
    op.create_index("ix_support_index_records_tenant_id", "support_index_records", ["tenant_id"])
    op.create_index("ix_support_index_records_provider", "support_index_records", ["provider"])
    op.create_index("ix_support_index_records_source_type", "support_index_records", ["source_type"])
    op.create_index("idx_support_index_tenant_provider", "support_index_records", ["tenant_id", "provider"])
    op.create_index(
        "idx_support_index_tenant_source",
        "support_index_records",
        ["tenant_id", "source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_support_index_tenant_source", table_name="support_index_records")
    op.drop_index("idx_support_index_tenant_provider", table_name="support_index_records")
    op.drop_index("ix_support_index_records_source_type", table_name="support_index_records")
    op.drop_index("ix_support_index_records_provider", table_name="support_index_records")
    op.drop_index("ix_support_index_records_tenant_id", table_name="support_index_records")
    op.drop_table("support_index_records")
