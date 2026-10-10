"""Create the durable agent run control store.

Revision ID: 0002_agent_control_store
Revises: 0001_analytics_baseline
"""

import sqlalchemy as sa
from alembic import op

revision = "0002_agent_control_store"
down_revision = "0001_analytics_baseline"
branch_labels = None
depends_on = None


def _append_only_triggers() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            """CREATE TRIGGER trg_agent_run_transitions_no_update
            BEFORE UPDATE ON analytics_run_transitions
            BEGIN SELECT RAISE(ABORT, 'agent transitions are append-only'); END"""
        )
        op.execute(
            """CREATE TRIGGER trg_agent_run_transitions_no_delete
            BEFORE DELETE ON analytics_run_transitions
            BEGIN SELECT RAISE(ABORT, 'agent transitions are append-only'); END"""
        )
        op.execute(
            """CREATE TRIGGER trg_agent_run_checkpoints_no_update
            BEFORE UPDATE ON analytics_run_checkpoints
            BEGIN SELECT RAISE(ABORT, 'agent checkpoints are append-only'); END"""
        )
        op.execute(
            """CREATE TRIGGER trg_agent_run_checkpoints_no_delete
            BEFORE DELETE ON analytics_run_checkpoints
            BEGIN SELECT RAISE(ABORT, 'agent checkpoints are append-only'); END"""
        )
        return
    if bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_agent_transition_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'agent transitions are append-only'; END; $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_agent_run_transitions_no_update
            BEFORE UPDATE OR DELETE ON analytics_run_transitions
            FOR EACH ROW EXECUTE FUNCTION reject_agent_transition_mutation()"""
        )
        op.execute(
            """CREATE FUNCTION reject_agent_checkpoint_mutation() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'agent checkpoints are append-only'; END; $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_agent_run_checkpoints_no_update
            BEFORE UPDATE OR DELETE ON analytics_run_checkpoints
            FOR EACH ROW EXECUTE FUNCTION reject_agent_checkpoint_mutation()"""
        )


def upgrade() -> None:
    op.create_table(
        "analytics_agent_runs",
        sa.Column("run_id", sa.String(length=255), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("current_node", sa.String(length=100), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column("transition_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("lease_fencing_seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.CheckConstraint("transition_seq >= 0", name="ck_agent_runs_transition_seq_nonnegative"),
        sa.CheckConstraint("lease_fencing_seq >= 0", name="ck_agent_runs_fencing_seq_nonnegative"),
        sa.CheckConstraint(
            "status IN ('active', 'waiting_approval', 'cancel_requested', 'terminal')", name="ck_agent_runs_status"
        ),
        sa.UniqueConstraint("run_id", "tenant_id", "purpose", name="uq_agent_run_identity"),
    )
    op.create_index("ix_agent_runs_tenant_status", "analytics_agent_runs", ["tenant_id", "status"])

    op.create_table(
        "analytics_run_checkpoints",
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("checkpoint_seq", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("state_version", sa.String(length=32), nullable=False),
        sa.Column("current_node", sa.String(length=100), nullable=False),
        sa.Column("transition_seq", sa.Integer(), nullable=False),
        sa.Column("lease_fencing_seq", sa.Integer(), nullable=False),
        sa.Column("state_payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("run_id", "checkpoint_seq"),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("run_id", "transition_seq", name="uq_agent_checkpoint_transition"),
        sa.CheckConstraint("checkpoint_seq >= 0", name="ck_agent_checkpoint_seq_nonnegative"),
        sa.CheckConstraint("transition_seq >= 0", name="ck_agent_checkpoint_transition_nonnegative"),
        sa.CheckConstraint("lease_fencing_seq >= 0", name="ck_agent_checkpoint_fencing_nonnegative"),
    )
    op.create_index("ix_agent_checkpoints_tenant_created", "analytics_run_checkpoints", ["tenant_id", "created_at"])

    op.create_table(
        "analytics_run_leases",
        sa.Column("run_id", sa.String(length=255), primary_key=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.String(length=255), nullable=False),
        sa.Column("lease_token", sa.String(length=255), nullable=False),
        sa.Column("fencing_seq", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "acquired_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column(
            "renewed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("lease_token", name="uq_agent_lease_token"),
        sa.CheckConstraint("fencing_seq > 0", name="ck_agent_lease_fencing_positive"),
    )
    op.create_index("ix_agent_leases_tenant_expiry", "analytics_run_leases", ["tenant_id", "expires_at"])

    op.create_table(
        "analytics_run_transitions",
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("transition_seq", sa.Integer(), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("graph_version", sa.String(length=64), nullable=False),
        sa.Column("from_node", sa.String(length=100), nullable=False),
        sa.Column("to_node", sa.String(length=100), nullable=True),
        sa.Column("from_status", sa.String(length=32), nullable=False),
        sa.Column("to_status", sa.String(length=32), nullable=False),
        sa.Column("fencing_seq", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("evidence_payload", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("run_id", "transition_seq"),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_agent_transition_idempotency"),
        sa.CheckConstraint("transition_seq > 0", name="ck_agent_transition_seq_positive"),
        sa.CheckConstraint("fencing_seq >= 0", name="ck_agent_transition_fencing_nonnegative"),
        sa.CheckConstraint(
            "from_status IN ('active', 'waiting_approval', 'cancel_requested') AND "
            "to_status IN ('active', 'waiting_approval', 'cancel_requested', 'terminal')",
            name="ck_agent_transition_status",
        ),
    )
    op.create_index("ix_agent_transitions_tenant_created", "analytics_run_transitions", ["tenant_id", "created_at"])
    _append_only_triggers()

    op.create_table(
        "analytics_run_outbox",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("run_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=100), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("delivery_status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "tenant_id", "purpose"],
            ["analytics_agent_runs.run_id", "analytics_agent_runs.tenant_id", "analytics_agent_runs.purpose"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("dedupe_key", name="uq_agent_outbox_dedupe"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_agent_outbox_attempts_nonnegative"),
        sa.CheckConstraint(
            "delivery_status IN ('queued', 'processing', 'delivered', 'failed')", name="ck_agent_outbox_status"
        ),
    )
    op.create_index("ix_agent_outbox_claim", "analytics_run_outbox", ["delivery_status", "available_at"])
    op.create_index("ix_agent_outbox_tenant_created", "analytics_run_outbox", ["tenant_id", "created_at"])


def downgrade() -> None:
    bind = op.get_bind()
    op.drop_index("ix_agent_outbox_tenant_created", table_name="analytics_run_outbox")
    op.drop_index("ix_agent_outbox_claim", table_name="analytics_run_outbox")
    op.drop_table("analytics_run_outbox")
    op.drop_index("ix_agent_transitions_tenant_created", table_name="analytics_run_transitions")
    op.drop_table("analytics_run_transitions")
    if bind.dialect.name == "postgresql":
        op.execute("DROP FUNCTION IF EXISTS reject_agent_transition_mutation()")
        op.execute("DROP FUNCTION IF EXISTS reject_agent_checkpoint_mutation()")
    op.drop_index("ix_agent_leases_tenant_expiry", table_name="analytics_run_leases")
    op.drop_table("analytics_run_leases")
    op.drop_index("ix_agent_checkpoints_tenant_created", table_name="analytics_run_checkpoints")
    op.drop_table("analytics_run_checkpoints")
    op.drop_index("ix_agent_runs_tenant_status", table_name="analytics_agent_runs")
    op.drop_table("analytics_agent_runs")
