# services/api/alembic/env.py
"""
Alembic environment configured for Compass.

Key choices:
  - Pull the database URL from app.config.settings (single source of truth)
  - Use the SYNC driver (psycopg2) here, even though the app uses asyncpg
    at runtime. Migrations are operational tasks, not request-path.
  - target_metadata = Base.metadata so 'alembic revision --autogenerate'
    catches new tables defined in the codebase.
"""
from logging.config import fileConfig
import os
import sys

from alembic import context
from sqlalchemy import engine_from_config, pool

# Add project root to sys.path so we can import the app package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings  # noqa: E402
from app.memory.postgres import Base  # noqa: E402

# Importing these registers their tables on Base.metadata
import app.context.models  # noqa: F401, E402
import app.threads.models  # noqa: F401, E402
import app.audit.models    # noqa: F401, E402

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Resolve URL from settings, force the sync driver for migrations
url = settings.get_database_url() if hasattr(settings, "get_database_url") else (settings.DATABASE_URL or "")
url = url.replace("+asyncpg", "")
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate raw SQL — useful for review without DB access."""
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
