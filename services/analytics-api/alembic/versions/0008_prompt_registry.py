"""Append-only registry of prompt and example versions.

Revision ID: 0008_prompt_registry
Revises: 0007_change_proposals
"""

import sqlalchemy as sa
from alembic import op

revision = "0008_prompt_registry"
down_revision = "0007_change_proposals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_prompt_registry",
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("tenant_id", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("scope", "tenant_id", "kind", "name", "version"),
        sa.CheckConstraint("status IN ('released', 'candidate')", name="ck_prompt_registry_status"),
        sa.CheckConstraint("scope IN ('system', 'tenant')", name="ck_prompt_registry_scope"),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"""CREATE TRIGGER trg_prompt_registry_no_{action.lower()} BEFORE {action} ON analytics_prompt_registry
                BEGIN SELECT RAISE(ABORT, 'the prompt registry is append-only'); END"""
            )
    elif bind.dialect.name == "postgresql":
        op.execute(
            """CREATE FUNCTION reject_prompt_registry_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'the prompt registry is append-only'; END; $$"""
        )
        op.execute(
            """CREATE TRIGGER trg_prompt_registry_no_mutation BEFORE UPDATE OR DELETE ON analytics_prompt_registry
            FOR EACH ROW EXECUTE FUNCTION reject_prompt_registry_mutation()"""
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_prompt_registry_no_mutation ON analytics_prompt_registry")
        op.execute("DROP FUNCTION IF EXISTS reject_prompt_registry_mutation()")
    op.drop_table("analytics_prompt_registry")
