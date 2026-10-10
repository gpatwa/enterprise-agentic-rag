"""Deterministic ADS-005 control-store invariants on SQLite."""

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

SERVICE_ROOT = Path(__file__).parent.parent


def _upgrade(database_url: str, monkeypatch):
    monkeypatch.setenv("ANALYTICS_CONTROL_DB_URL", database_url)
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    command.upgrade(config, "head")
    return config


def _run_row(connection, run_id="run-1"):
    connection.execute(
        text("""INSERT INTO analytics_agent_runs
        (run_id, tenant_id, purpose, graph_version, state_version, current_node, state_payload)
        VALUES (:run_id, 'tenant-a', 'analytics', 'g-1', 'v1', 'bootstrap', '{}')"""),
        {"run_id": run_id},
    )


def test_migration_exposes_control_store_and_constraints(tmp_path, monkeypatch):
    config = _upgrade(f"sqlite:///{tmp_path / 'control.db'}", monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    tables = set(inspect(engine).get_table_names())
    assert {
        "analytics_agent_runs",
        "analytics_run_checkpoints",
        "analytics_run_leases",
        "analytics_run_transitions",
        "analytics_run_outbox",
    } <= tables
    assert {c["name"] for c in inspect(engine).get_columns("analytics_agent_runs")} >= {
        "tenant_id",
        "state_payload",
        "transition_seq",
        "lease_fencing_seq",
    }
    command.downgrade(config, "base")
    assert inspect(engine).get_table_names() == ["alembic_version"]


def test_checkpoint_is_resume_boundary_and_duplicate_sequence_is_rejected(tmp_path, monkeypatch):
    _upgrade(f"sqlite:///{tmp_path / 'control.db'}", monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    with engine.begin() as connection:
        _run_row(connection)
        connection.execute(
            text("""INSERT INTO analytics_run_checkpoints
            (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node,
             transition_seq, lease_fencing_seq, state_payload)
            VALUES ('run-1', 1, 'tenant-a', 'analytics', 'g-1', 'v1', 'retrieve', 1, 1, '{"step": "retrieve"}')""")
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text("""INSERT INTO analytics_run_checkpoints
                (run_id, checkpoint_seq, tenant_id, purpose, graph_version, state_version, current_node,
                 transition_seq, lease_fencing_seq, state_payload)
                VALUES ('run-1', 2, 'tenant-a', 'analytics', 'g-1', 'v1', 'resolve', 1, 1, '{}')""")
            )


def test_stale_fencing_and_non_monotonic_transitions_are_rejected(tmp_path, monkeypatch):
    _upgrade(f"sqlite:///{tmp_path / 'control.db'}", monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    with engine.begin() as connection:
        _run_row(connection)
        connection.execute(
            text("""INSERT INTO analytics_run_leases
            (run_id, tenant_id, purpose, owner_id, lease_token, fencing_seq, expires_at)
            VALUES ('run-1', 'tenant-a', 'analytics', 'worker-a', 'lease-1', 2, CURRENT_TIMESTAMP)""")
        )
        connection.execute(
            text("""INSERT INTO analytics_run_transitions
            (run_id, transition_seq, tenant_id, purpose, graph_version, from_node, to_node, from_status, to_status, fencing_seq, idempotency_key)
            VALUES ('run-1', 1, 'tenant-a', 'analytics', 'g-1', 'create', 'bootstrap', 'active', 'active', 2, 't-1')""")
        )
        with pytest.raises(IntegrityError):
            connection.execute(
                text("""INSERT INTO analytics_run_transitions
                (run_id, transition_seq, tenant_id, purpose, graph_version, from_node, to_node, from_status, to_status, fencing_seq, idempotency_key)
                VALUES ('run-1', 1, 'tenant-a', 'analytics', 'g-1', 'bootstrap', 'retrieve', 'active', 'active', 1, 't-stale')""")
            )
        with pytest.raises((OperationalError, IntegrityError)):
            connection.execute(text("UPDATE analytics_run_transitions SET to_node = 'tampered' WHERE run_id = 'run-1'"))


def test_outbox_dedupe_allows_one_delivery_record(tmp_path, monkeypatch):
    _upgrade(f"sqlite:///{tmp_path / 'control.db'}", monkeypatch)
    engine = create_engine(f"sqlite:///{tmp_path / 'control.db'}")
    with engine.begin() as connection:
        _run_row(connection)
        statement = text("""INSERT INTO analytics_run_outbox
            (tenant_id, run_id, purpose, event_type, dedupe_key, payload)
            VALUES ('tenant-a', 'run-1', 'analytics', 'checkpoint', 'run-1:1', '{}')""")
        connection.execute(statement)
        with pytest.raises(IntegrityError):
            connection.execute(statement)
