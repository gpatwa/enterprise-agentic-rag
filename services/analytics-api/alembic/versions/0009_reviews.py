"""Append-only reviews and their audit events.

Revision ID: 0009_reviews
Revises: 0008_prompt_registry
"""

import sqlalchemy as sa
from alembic import op

revision = "0009_reviews"
down_revision = "0008_prompt_registry"
branch_labels = None
depends_on = None

_TABLES = ("analytics_reviews", "analytics_review_events")


def upgrade() -> None:
    op.create_table(
        "analytics_reviews",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("review_id", sa.String(length=255), nullable=False),
        sa.Column("purpose", sa.String(length=255), nullable=False),
        sa.Column("subject_kind", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.String(length=255), nullable=False),
        sa.Column("subject_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("requested_by", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")
        ),
        sa.PrimaryKeyConstraint("tenant_id", "review_id"),
    )
    op.create_index(
        "ix_reviews_subject", "analytics_reviews", ["tenant_id", "subject_kind", "subject_id", "subject_fingerprint"]
    )
    op.create_table(
        "analytics_review_events",
        sa.Column("tenant_id", sa.String(length=255), nullable=False),
        sa.Column("review_id", sa.String(length=255), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("actor", sa.String(length=255), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tenant_id", "review_id", "seq"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "review_id"], ["analytics_reviews.tenant_id", "analytics_reviews.review_id"]
        ),
        sa.CheckConstraint("seq > 0", name="ck_review_events_seq_positive"),
    )
    bind = op.get_bind()
    for table in _TABLES:
        if bind.dialect.name == "sqlite":
            for action in ("UPDATE", "DELETE"):
                op.execute(
                    f"""CREATE TRIGGER trg_{table}_no_{action.lower()} BEFORE {action} ON {table}
                    BEGIN SELECT RAISE(ABORT, '{table} is append-only'); END"""
                )
        elif bind.dialect.name == "postgresql":
            op.execute(
                f"""CREATE FUNCTION reject_{table}_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION '{table} is append-only'; END; $$"""
            )
            op.execute(
                f"""CREATE TRIGGER trg_{table}_no_mutation BEFORE UPDATE OR DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION reject_{table}_mutation()"""
            )


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(_TABLES):
        if bind.dialect.name == "postgresql":
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_mutation ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS reject_{table}_mutation()")
    op.drop_table("analytics_review_events")
    op.drop_index("ix_reviews_subject", table_name="analytics_reviews")
    op.drop_table("analytics_reviews")
