from __future__ import annotations

import importlib
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


def test_search_outbox_migration_up_down_and_unique_idempotency(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0006_support_search_outbox.py"
    )
    spec = importlib.util.spec_from_file_location("support_search_outbox_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")

    with engine.begin() as connection:
        operations = Operations(MigrationContext.configure(connection))
        monkeypatch.setattr(migration, "op", operations)
        migration.upgrade()

        inspector = inspect(connection)
        assert "support_search_outbox" in inspector.get_table_names()
        assert "support_search_checkpoints" in inspector.get_table_names()
        outbox_columns = {column["name"] for column in inspector.get_columns("support_search_outbox")}
        assert {"idempotency_key", "status", "available_at"}.issubset(outbox_columns)

        connection.execute(
            text(
                "INSERT INTO support_search_outbox "
                "(idempotency_key, tenant_id, provider, event_type, source_type, source_id) "
                "VALUES ('event-1', 'tenant-a', 'zendesk', 'upsert', 'ticket', '42')"
            )
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO support_search_outbox "
                    "(idempotency_key, tenant_id, provider, event_type, source_type, source_id) "
                    "VALUES ('event-1', 'tenant-a', 'zendesk', 'upsert', 'ticket', '43')"
                )
            )

        migration.downgrade()
        assert "support_search_outbox" not in inspect(connection).get_table_names()
        assert "support_search_checkpoints" not in inspect(connection).get_table_names()
