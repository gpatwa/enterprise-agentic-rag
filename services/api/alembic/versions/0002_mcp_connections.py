"""mcp_connections — per-tenant ↔ per-server MCP credentials

Revision ID: 0002_mcp_connections
Revises: 0001_baseline
Create Date: 2026-05-04 14:00:00

Adds the `mcp_connections` table that backs the MCP integration. One row
per (tenant_id, server_name); credentials are Fernet-encrypted text.

The table is also created opportunistically by `Base.metadata.create_all()`
on first boot (see app/memory/postgres.py), but the migration ensures
schema-managed environments get the explicit DDL + indexes.
"""
import sqlalchemy as sa
from alembic import op

revision = "0002_mcp_connections"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mcp_connections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("server_name", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column("encrypted_config", sa.Text(), nullable=False),
        sa.Column("last_health_check", sa.DateTime(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint(
            "tenant_id", "server_name", name="uq_mcp_tenant_server"
        ),
    )
    op.create_index(
        "ix_mcp_connections_tenant_id", "mcp_connections", ["tenant_id"]
    )
    op.create_index(
        "ix_mcp_connections_server_name", "mcp_connections", ["server_name"]
    )
    op.create_index(
        "idx_mcp_tenant_status", "mcp_connections", ["tenant_id", "status"]
    )


def downgrade() -> None:
    op.drop_index("idx_mcp_tenant_status", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_server_name", table_name="mcp_connections")
    op.drop_index("ix_mcp_connections_tenant_id", table_name="mcp_connections")
    op.drop_table("mcp_connections")
