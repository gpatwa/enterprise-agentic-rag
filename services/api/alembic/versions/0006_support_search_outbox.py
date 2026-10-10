"""durable enterprise search outbox and checkpoints

Revision ID: 0006_support_search_outbox
Revises: 0005_support_jobs
Create Date: 2026-08-22 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0006_support_search_outbox"
down_revision = "0005_support_jobs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_search_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_id", sa.String(length=255), nullable=False),
        sa.Column("content_version", sa.String(length=255), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("available_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("locked_by", sa.String(length=255), nullable=True),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("idempotency_key", name="uq_support_search_outbox_idempotency"),
    )
    op.create_index("ix_support_search_outbox_tenant_id", "support_search_outbox", ["tenant_id"])
    op.create_index("ix_support_search_outbox_provider", "support_search_outbox", ["provider"])
    op.create_index("ix_support_search_outbox_event_type", "support_search_outbox", ["event_type"])
    op.create_index("ix_support_search_outbox_status", "support_search_outbox", ["status"])
    op.create_index(
        "idx_support_search_outbox_claim",
        "support_search_outbox",
        ["status", "available_at", "locked_at"],
    )
    op.create_index(
        "idx_support_search_outbox_tenant_source",
        "support_search_outbox",
        ["tenant_id", "source_type", "source_id"],
    )

    op.create_table(
        "support_search_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("stream_key", sa.String(length=255), nullable=False),
        sa.Column("cursor", sa.String(length=1000), nullable=True),
        sa.Column("last_event_id", sa.String(length=255), nullable=True),
        sa.Column("last_source_updated_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "stream_key",
            name="uq_support_search_checkpoint_stream",
        ),
    )
    op.create_index("ix_support_search_checkpoints_tenant_id", "support_search_checkpoints", ["tenant_id"])
    op.create_index("ix_support_search_checkpoints_provider", "support_search_checkpoints", ["provider"])
    op.create_index(
        "idx_support_search_checkpoint_tenant_provider",
        "support_search_checkpoints",
        ["tenant_id", "provider"],
    )


def downgrade() -> None:
    op.drop_index("idx_support_search_checkpoint_tenant_provider", table_name="support_search_checkpoints")
    op.drop_index("ix_support_search_checkpoints_provider", table_name="support_search_checkpoints")
    op.drop_index("ix_support_search_checkpoints_tenant_id", table_name="support_search_checkpoints")
    op.drop_table("support_search_checkpoints")

    op.drop_index("idx_support_search_outbox_tenant_source", table_name="support_search_outbox")
    op.drop_index("idx_support_search_outbox_claim", table_name="support_search_outbox")
    op.drop_index("ix_support_search_outbox_status", table_name="support_search_outbox")
    op.drop_index("ix_support_search_outbox_event_type", table_name="support_search_outbox")
    op.drop_index("ix_support_search_outbox_provider", table_name="support_search_outbox")
    op.drop_index("ix_support_search_outbox_tenant_id", table_name="support_search_outbox")
    op.drop_table("support_search_outbox")
