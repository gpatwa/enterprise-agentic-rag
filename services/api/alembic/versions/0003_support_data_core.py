"""support data core for ticket resolution intelligence

Revision ID: 0003_support_data_core
Revises: 0002_mcp_connections
Create Date: 2026-05-30 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0003_support_data_core"
down_revision = "0002_mcp_connections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "support_integration_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("auth_mode", sa.String(length=32), nullable=False, server_default="nango"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("nango_connection_id", sa.String(length=255), nullable=True),
        sa.Column("provider_config_key", sa.String(length=255), nullable=True),
        sa.Column("external_account_id", sa.String(length=255), nullable=True),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("last_health_check", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "provider", name="uq_support_conn_tenant_provider"),
    )
    op.create_index("ix_support_integration_connections_tenant_id", "support_integration_connections", ["tenant_id"])
    op.create_index("ix_support_integration_connections_provider", "support_integration_connections", ["provider"])
    op.create_index("idx_support_conn_tenant_status", "support_integration_connections", ["tenant_id", "status"])

    op.create_table(
        "support_customers",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=500), nullable=True),
        sa.Column("name", sa.String(length=500), nullable=True),
        sa.Column("role", sa.String(length=100), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "provider", "external_id", name="uq_support_customer"),
    )
    op.create_index("ix_support_customers_tenant_id", "support_customers", ["tenant_id"])
    op.create_index("ix_support_customers_provider", "support_customers", ["provider"])
    op.create_index("idx_support_customer_tenant_provider", "support_customers", ["tenant_id", "provider"])
    op.create_index("idx_support_customer_tenant_email", "support_customers", ["tenant_id", "email"])

    op.create_table(
        "support_tickets",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("subject", sa.String(length=1000), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=100), nullable=True),
        sa.Column("priority", sa.String(length=100), nullable=True),
        sa.Column("category", sa.String(length=100), nullable=True),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("requester_external_id", sa.String(length=255), nullable=True),
        sa.Column("assignee_external_id", sa.String(length=255), nullable=True),
        sa.Column("organization_external_id", sa.String(length=255), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=True),
        sa.Column("custom_fields", sa.JSON(), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("source_url", sa.String(length=1500), nullable=True),
        sa.Column("created_at_external", sa.DateTime(), nullable=True),
        sa.Column("updated_at_external", sa.DateTime(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "provider", "external_id", name="uq_support_ticket"),
    )
    op.create_index("ix_support_tickets_tenant_id", "support_tickets", ["tenant_id"])
    op.create_index("ix_support_tickets_provider", "support_tickets", ["provider"])
    op.create_index("ix_support_tickets_status", "support_tickets", ["status"])
    op.create_index("idx_support_ticket_tenant_provider_status", "support_tickets", ["tenant_id", "provider", "status"])
    op.create_index("idx_support_ticket_tenant_updated", "support_tickets", ["tenant_id", "updated_at_external"])
    op.create_index("idx_support_ticket_requester", "support_tickets", ["tenant_id", "provider", "requester_external_id"])

    op.create_table(
        "support_ticket_comments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("ticket_external_id", sa.String(length=255), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("author_external_id", sa.String(length=255), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("created_at_external", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint(
            "tenant_id",
            "provider",
            "ticket_external_id",
            "external_id",
            name="uq_support_ticket_comment",
        ),
    )
    op.create_index("ix_support_ticket_comments_tenant_id", "support_ticket_comments", ["tenant_id"])
    op.create_index("ix_support_ticket_comments_provider", "support_ticket_comments", ["provider"])
    op.create_index("idx_support_comment_ticket", "support_ticket_comments", ["tenant_id", "provider", "ticket_external_id"])

    op.create_table(
        "support_articles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("locale", sa.String(length=50), nullable=True),
        sa.Column("source_url", sa.String(length=1500), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("updated_at_external", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("tenant_id", "provider", "external_id", name="uq_support_article"),
    )
    op.create_index("ix_support_articles_tenant_id", "support_articles", ["tenant_id"])
    op.create_index("ix_support_articles_provider", "support_articles", ["provider"])
    op.create_index("idx_support_article_tenant_provider", "support_articles", ["tenant_id", "provider"])

    op.create_table(
        "support_sync_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="running"),
        sa.Column("cursor_started_at", sa.String(length=100), nullable=True),
        sa.Column("cursor_finished_at", sa.String(length=100), nullable=True),
        sa.Column("records_seen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_upserted", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("records_skipped", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("metadata_", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
    )
    op.create_index("ix_support_sync_runs_tenant_id", "support_sync_runs", ["tenant_id"])
    op.create_index("ix_support_sync_runs_provider", "support_sync_runs", ["provider"])
    op.create_index("idx_support_sync_tenant_provider_started", "support_sync_runs", ["tenant_id", "provider", "started_at"])
    op.create_index("idx_support_sync_tenant_status", "support_sync_runs", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_index("idx_support_sync_tenant_status", table_name="support_sync_runs")
    op.drop_index("idx_support_sync_tenant_provider_started", table_name="support_sync_runs")
    op.drop_index("ix_support_sync_runs_provider", table_name="support_sync_runs")
    op.drop_index("ix_support_sync_runs_tenant_id", table_name="support_sync_runs")
    op.drop_table("support_sync_runs")

    op.drop_index("idx_support_article_tenant_provider", table_name="support_articles")
    op.drop_index("ix_support_articles_provider", table_name="support_articles")
    op.drop_index("ix_support_articles_tenant_id", table_name="support_articles")
    op.drop_table("support_articles")

    op.drop_index("idx_support_comment_ticket", table_name="support_ticket_comments")
    op.drop_index("ix_support_ticket_comments_provider", table_name="support_ticket_comments")
    op.drop_index("ix_support_ticket_comments_tenant_id", table_name="support_ticket_comments")
    op.drop_table("support_ticket_comments")

    op.drop_index("idx_support_ticket_requester", table_name="support_tickets")
    op.drop_index("idx_support_ticket_tenant_updated", table_name="support_tickets")
    op.drop_index("idx_support_ticket_tenant_provider_status", table_name="support_tickets")
    op.drop_index("ix_support_tickets_status", table_name="support_tickets")
    op.drop_index("ix_support_tickets_provider", table_name="support_tickets")
    op.drop_index("ix_support_tickets_tenant_id", table_name="support_tickets")
    op.drop_table("support_tickets")

    op.drop_index("idx_support_customer_tenant_email", table_name="support_customers")
    op.drop_index("idx_support_customer_tenant_provider", table_name="support_customers")
    op.drop_index("ix_support_customers_provider", table_name="support_customers")
    op.drop_index("ix_support_customers_tenant_id", table_name="support_customers")
    op.drop_table("support_customers")

    op.drop_index("idx_support_conn_tenant_status", table_name="support_integration_connections")
    op.drop_index("ix_support_integration_connections_provider", table_name="support_integration_connections")
    op.drop_index("ix_support_integration_connections_tenant_id", table_name="support_integration_connections")
    op.drop_table("support_integration_connections")
