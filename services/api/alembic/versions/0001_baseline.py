"""baseline — capture the existing schema

Revision ID: 0001_baseline
Revises:
Create Date: 2026-05-04 12:00:00

This baseline is intentionally a no-op. It marks the state where every
table in app.memory.Base.metadata was already created by `Base.metadata.
create_all()` on first boot. From this point forward, schema changes
ship as new revisions.

To stamp an existing database with this baseline:

    cd services/api
    DATABASE_URL=... alembic stamp 0001_baseline

To create a new schema change:

    alembic revision --autogenerate -m "add foo column"
    alembic upgrade head
"""
import sqlalchemy as sa  # noqa: F401
from alembic import op  # noqa: F401

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No-op: existing schema already created by Base.metadata.create_all().
    # Future revisions add real DDL here.
    pass


def downgrade() -> None:
    # No-op for the baseline.
    pass
