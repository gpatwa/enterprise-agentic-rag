"""Run database migrations, adopting a schema the API already created.

The API creates its tables with ``Base.metadata.create_all`` on start, and the Alembic baseline (0001) is a documented
no-op for a schema created that way. When the API started before any migration ran (for example the first Helm install
without the migration hook), the tables exist but ``alembic_version`` does not, and ``alembic upgrade head`` fails on the
first ``CREATE TABLE`` with ``relation ... already exists``.

This runner decides once per run:
  - the database is versioned                         -> ``upgrade head``
  - unversioned, and every model table already exists -> ``stamp head`` (record the revision, run no DDL)
  - otherwise (fresh or partial)                      -> ``upgrade head`` (a partial schema fails loudly, as before)

Used as the Helm migration job's command: ``python alembic_runner.py``.
"""

from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def decide(has_version_table: bool, existing_tables: set[str], model_tables: set[str]) -> str:
    """Return ``"upgrade"`` or ``"stamp"``."""
    if has_version_table:
        return "upgrade"
    if model_tables and model_tables <= existing_tables:
        return "stamp"
    return "upgrade"


def _model_tables() -> set[str]:
    import app.audit.models  # noqa: F401  (registers tables on Base.metadata, as alembic/env.py does)
    import app.context.models  # noqa: F401
    import app.threads.models  # noqa: F401
    from app.memory.postgres import Base

    return set(Base.metadata.tables)


def _database_url() -> str:
    from app.config import settings

    url = settings.get_database_url() if hasattr(settings, "get_database_url") else (settings.DATABASE_URL or "")
    return url.replace("+asyncpg", "")


def main() -> int:
    sys.path.insert(0, HERE)
    os.chdir(HERE)
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    engine = create_engine(_database_url())
    try:
        existing = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    action = decide("alembic_version" in existing, existing, _model_tables())
    config = Config(os.path.join(HERE, "alembic.ini"))
    if action == "stamp":
        print("Schema exists without a migration record: stamping head (no DDL).", flush=True)
        command.stamp(config, "head")
    else:
        print("Running alembic upgrade head.", flush=True)
        command.upgrade(config, "head")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
