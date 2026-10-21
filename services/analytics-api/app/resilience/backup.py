"""Logical backup and verified restore of the analytics control store (ADS-068).

The control store holds runs, checkpoints, transitions, reviews, feedback, evidence, and the learning-loop records. A backup is a
directory of per-table JSON-lines files plus a manifest (schema revision, row counts, per-table and overall digests). It works on
SQLite and PostgreSQL alike because it uses only SQL and the table dependency order. Run leases are deliberately not backed up:
a restored worker must acquire new leases. Restore refuses a corrupt backup, a different schema revision, or a non-empty target,
writes in one transaction, and then re-verifies counts, digests, and every tenant's evidence chain.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, MetaData, inspect, text

from app.runtime.evidence_store import EvidenceStore
from packages.platform_contracts.resilience import ControlBackupManifest, TableBackup

EXCLUDED_TABLES = frozenset({"alembic_version", "analytics_run_leases"})
_NAME = re.compile(r"^[a-z][a-z0-9_]*$")


class ResilienceError(Exception):
    """A backup or restore was refused; `code` is stable and carries no row content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _tables(engine: Engine) -> list[str]:
    metadata = MetaData()
    metadata.reflect(bind=engine)
    names = [table.name for table in metadata.sorted_tables if table.name not in EXCLUDED_TABLES]
    for name in names:
        if not _NAME.match(name):  # table names go into SQL text; reflected names are checked first
            raise ResilienceError("unsafe_table_name")
    return names


def _order_by(engine: Engine, table: str) -> str:
    inspector = inspect(engine)
    keys = inspector.get_pk_constraint(table).get("constrained_columns") or [
        c["name"] for c in inspector.get_columns(table)
    ]
    return ", ".join(f'"{key}"' for key in keys)


def _encode(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (bytes, bytearray)):
        return {"__hex__": bytes(value).hex()}
    return value


def _decode_for_bind(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"__hex__"}:
        return bytes.fromhex(value["__hex__"])
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"))  # JSON columns take their text form, as the store writes them
    return value


def _dump_rows(engine: Engine, table: str, connection: Any = None) -> list[str]:
    order = _order_by(engine, table)
    if connection is None:
        with engine.connect() as own:
            rows = own.execute(text(f'SELECT * FROM "{table}" ORDER BY {order}')).mappings().all()
    else:
        rows = connection.execute(text(f'SELECT * FROM "{table}" ORDER BY {order}')).mappings().all()
    return [
        json.dumps(
            {key: _encode(value) for key, value in row.items()}, sort_keys=True, separators=(",", ":"), default=str
        )
        for row in rows
    ]


def _reset_sequences(connection: Any, engine: Engine, tables: list[str]) -> None:
    """After inserting explicit ids, move every serial sequence past them (PostgreSQL only; SQLite has none)."""
    if connection.dialect.name != "postgresql":
        return
    inspector = inspect(engine)
    for table in tables:
        for column in inspector.get_columns(table):
            name = column["name"]
            sequence = connection.execute(
                text("SELECT pg_get_serial_sequence(:table, :column)"), {"table": f'"{table}"', "column": name}
            ).scalar()
            if sequence:
                connection.execute(
                    text(
                        f'SELECT setval(:sequence, COALESCE(MAX("{name}"), 1), MAX("{name}") IS NOT NULL) FROM "{table}"'
                    ),
                    {"sequence": sequence},
                )


def _digest(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()


def _overall(tables: dict[str, TableBackup], revision: str) -> str:
    material = revision + "\n" + "\n".join(f"{name}:{info.rows}:{info.digest}" for name, info in sorted(tables.items()))
    return hashlib.sha256(material.encode()).hexdigest()


def _revision(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar())


def backup_control_store(
    engine: Engine, destination: Path | str, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
) -> ControlBackupManifest:
    destination = Path(destination)
    if destination.exists():
        raise ResilienceError("backup_destination_exists")
    destination.mkdir(parents=True)
    tables: dict[str, TableBackup] = {}
    revision = _revision(engine)
    names = _tables(engine)
    # One read transaction for every table, so the backup is a consistent snapshot even while runs are in flight.
    with engine.connect() as connection, connection.begin():
        if connection.dialect.name == "postgresql":
            connection.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        dumps = {name: _dump_rows(engine, name, connection) for name in names}
    for name, lines in dumps.items():
        (destination / f"{name}.jsonl").write_text("".join(line + "\n" for line in lines))
        tables[name] = TableBackup(rows=len(lines), digest=_digest(lines))
    manifest = ControlBackupManifest(
        backup_id=uuid.uuid4().hex,
        created_at=clock(),
        schema_revision=revision,
        tables=tables,
        digest=_overall(tables, revision),
    )
    (destination / "manifest.json").write_text(manifest.model_dump_json(indent=2))
    return manifest


def verify_backup_files(source: Path | str) -> ControlBackupManifest:
    """Check a backup directory against its own manifest without touching any database."""
    source = Path(source)
    try:
        manifest = ControlBackupManifest.model_validate_json((source / "manifest.json").read_text())
    except (OSError, ValueError) as exc:
        raise ResilienceError("backup_manifest_unreadable") from exc
    if manifest.digest != _overall(manifest.tables, manifest.schema_revision):
        raise ResilienceError("backup_manifest_tampered")
    for name, info in manifest.tables.items():
        path = source / f"{name}.jsonl"
        if not path.is_file():
            raise ResilienceError("backup_table_missing")
        lines = path.read_text().splitlines()
        if len(lines) != info.rows or _digest(lines) != info.digest:
            raise ResilienceError("backup_corrupt")
    return manifest


def restore_control_store(source: Path | str, engine: Engine) -> dict[str, Any]:
    """Restore into an empty database already migrated to the backup's schema revision; verify afterwards."""
    source = Path(source)
    manifest = verify_backup_files(source)
    if _revision(engine) != manifest.schema_revision:
        raise ResilienceError("schema_revision_mismatch")
    targets = _tables(engine)
    if set(targets) != set(manifest.tables):
        raise ResilienceError("schema_tables_mismatch")
    with engine.connect() as connection:
        for name in targets:
            if connection.execute(text(f'SELECT COUNT(*) FROM "{name}"')).scalar():
                raise ResilienceError("target_not_empty")
    with engine.begin() as connection:  # all or nothing
        for name in targets:
            rows = [json.loads(line) for line in (source / f"{name}.jsonl").read_text().splitlines()]
            if not rows:
                continue
            columns = list(rows[0])
            statement = text(
                f'INSERT INTO "{name}" ({", ".join(chr(34) + c + chr(34) for c in columns)}) '
                f"VALUES ({', '.join(':' + c for c in columns)})"
            )
            connection.execute(statement, [{c: _decode_for_bind(row[c]) for c in columns} for row in rows])
        _reset_sequences(connection, engine, targets)
    restored = {
        name: TableBackup(rows=len(lines), digest=_digest(lines))
        for name in targets
        for lines in [_dump_rows(engine, name)]
    }
    if restored != manifest.tables:
        raise ResilienceError("restore_verification_failed")
    with engine.connect() as connection:
        tenants = [
            r[0] for r in connection.execute(text("SELECT DISTINCT tenant_id FROM analytics_evidence_envelopes")).all()
        ]
    chain = EvidenceStore(engine)
    sealed = 0
    for tenant in tenants:
        try:
            sealed += chain.verify_chain(tenant)
        except Exception as exc:  # noqa: BLE001 - any broken chain fails the restore; row content is not reported.
            raise ResilienceError("restored_evidence_chain_broken") from exc
    return {
        "backup_id": manifest.backup_id,
        "tables": len(targets),
        "rows": manifest.object_count,
        "evidence_envelopes": sealed,
    }
