"""persist consented search interaction events

Revision ID: 0007_search_interaction_events
Revises: 0006_support_search_outbox
Create Date: 2026-08-23 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0007_search_interaction_events"
down_revision = "0006_support_search_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_interaction_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("principal_pseudonym", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("request_id", sa.String(length=255), nullable=True),
        sa.Column("document_id", sa.String(length=255), nullable=True),
        sa.Column("query_hash", sa.String(length=128), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_granted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("metadata_json", sa.JSON(), nullable=False),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_search_interaction_idempotency"),
    )
    op.create_index("idx_search_interaction_tenant_expiry", "search_interaction_events", ["tenant_id", "expires_at"])
    op.create_index("idx_search_interaction_tenant_document", "search_interaction_events", ["tenant_id", "document_id"])


def downgrade() -> None:
    op.drop_index("idx_search_interaction_tenant_document", table_name="search_interaction_events")
    op.drop_index("idx_search_interaction_tenant_expiry", table_name="search_interaction_events")
    op.drop_table("search_interaction_events")
