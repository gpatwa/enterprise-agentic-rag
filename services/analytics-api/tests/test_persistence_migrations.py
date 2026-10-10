"""Executable upgrade/downgrade checks for the Analytics control-store schema."""
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

SERVICE_ROOT = Path(__file__).parent.parent


def test_analytics_migrations_upgrade_and_downgrade_an_empty_database(tmp_path, monkeypatch):
    database_path = tmp_path / "analytics-control.db"
    database_url = f"sqlite:///{database_path}"
    monkeypatch.setenv("ANALYTICS_CONTROL_DB_URL", database_url)

    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)
    assert "analytics_query_outcomes" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("analytics_query_outcomes")}
    assert {"query_id", "tenant_id", "outcome", "response_payload", "evidence_payload"} <= columns

    command.downgrade(config, "base")
    assert "analytics_query_outcomes" not in inspect(engine).get_table_names()
