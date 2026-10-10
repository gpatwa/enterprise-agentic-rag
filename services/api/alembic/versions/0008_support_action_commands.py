"""persist typed support command proposals

Revision ID: 0008_support_action_commands
Revises: 0007_search_interaction_events
Create Date: 2026-08-23 00:00:00
"""
import sqlalchemy as sa
from alembic import op

revision = "0008_support_action_commands"
down_revision = "0007_search_interaction_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("support_actions"):
        op.create_table(
            "support_actions",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("tenant_id", sa.String(length=255), nullable=False),
            sa.Column("created_by", sa.String(length=255), nullable=False),
            sa.Column("action_type", sa.String(length=64), nullable=False, server_default="support_agent_command"),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="generated"),
            sa.Column("cluster_id", sa.String(length=255), nullable=True),
            sa.Column("cluster_title", sa.String(length=500), nullable=False),
            sa.Column("command_text", sa.Text(), nullable=False),
            sa.Column("workflow", sa.JSON(), nullable=True),
            sa.Column("review_notes", sa.Text(), nullable=True),
            sa.Column("approved_by", sa.String(length=255), nullable=True),
            sa.Column("approved_at", sa.DateTime(), nullable=True),
            sa.Column("ready_at", sa.DateTime(), nullable=True),
            sa.Column("executed_by", sa.String(length=255), nullable=True),
            sa.Column("executed_at", sa.DateTime(), nullable=True),
            sa.Column("execution_result", sa.JSON(), nullable=True),
            sa.Column("rejected_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index(
            "idx_support_action_tenant_status_created",
            "support_actions",
            ["tenant_id", "status", "created_at"],
        )
        op.create_index(
            "idx_support_action_tenant_cluster",
            "support_actions",
            ["tenant_id", "cluster_id"],
        )

    op.add_column("support_actions", sa.Column("command_contract_version", sa.String(length=32), nullable=True))
    op.add_column("support_actions", sa.Column("command_payload", sa.JSON(), nullable=True))
    op.add_column("support_actions", sa.Column("policy_status", sa.String(length=32), nullable=True))
    op.add_column("support_actions", sa.Column("policy_reason", sa.Text(), nullable=True))
    op.add_column("support_actions", sa.Column("evidence_ids", sa.JSON(), nullable=True))
    op.add_column("support_actions", sa.Column("idempotency_key", sa.String(length=255), nullable=True))
    op.create_unique_constraint(
        "uq_support_action_tenant_idempotency",
        "support_actions",
        ["tenant_id", "idempotency_key"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_support_action_tenant_idempotency", "support_actions", type_="unique")
    op.drop_column("support_actions", "idempotency_key")
    op.drop_column("support_actions", "evidence_ids")
    op.drop_column("support_actions", "policy_reason")
    op.drop_column("support_actions", "policy_status")
    op.drop_column("support_actions", "command_payload")
    op.drop_column("support_actions", "command_contract_version")
