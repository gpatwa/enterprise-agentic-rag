"""Embedded DuckDB gateway: allowlisted files only, no external access, interruptible."""

from __future__ import annotations

import json
import re
import threading
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import duckdb

from app.execution.gateway import (
    CancellationToken,
    CostLimitExceeded,
    DialectMismatch,
    ExecutionCancelled,
    ExecutionError,
    ExecutionLimits,
    ExecutionResult,
    ExecutionTimeout,
    ResultAccumulator,
)
from app.execution.validation import validate_read_only_sql

_READERS = {".parquet": "read_parquet", ".csv": "read_csv_auto"}
_NAMED_PARAMETER = re.compile(r"(?<![:\w]):(p\d+)\b")
_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class DuckDBGateway:
    """Each execution gets a fresh in-memory database exposing only registered files.

    After the views are created the connection drops external access and locks its
    configuration, so a query cannot read other files, attach databases, write, or
    re-enable access, whatever SQL reaches it.
    """

    dialect = "duckdb"

    def __init__(
        self,
        sources: Mapping[str, Path | str],
        *,
        allowed_root: Path | str,
        memory_limit: str = "512MB",
        threads: int = 2,
    ) -> None:
        root = Path(allowed_root).resolve()
        resolved: dict[str, Path] = {}
        for table, raw in sources.items():
            if not _TABLE_NAME.match(table):
                raise ValueError(f"invalid table name: {table!r}")
            path = Path(raw).resolve()
            if root != path and root not in path.parents:
                raise PermissionError(f"DuckDB source for {table} is outside the allowed root")
            if path.suffix.lower() not in _READERS:
                raise ValueError(f"unsupported DuckDB source type: {path.suffix}")
            if not path.is_file():
                raise FileNotFoundError(f"DuckDB source for {table} does not exist")
            resolved[table] = path
        if not resolved:
            raise ValueError("at least one DuckDB source is required")
        self._sources = resolved
        self._memory_limit = memory_limit
        self._threads = threads

    def estimate(self, plan: Any) -> float:
        """Sum of planner-estimated cardinalities across operators (rows touched)."""
        sql, parameters = self._prepare(plan)
        connection = self._connect()
        try:
            rows = connection.execute(f"EXPLAIN (FORMAT JSON) {sql}", parameters).fetchall()
            return _total_cardinality(json.loads(rows[0][1]))
        except ExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - an unknown estimate must not execute.
            raise ExecutionError("cost estimate failed") from exc
        finally:
            connection.close()

    def execute(
        self,
        plan: Any,
        *,
        limits: ExecutionLimits,
        cancellation: CancellationToken | None = None,
    ) -> ExecutionResult:
        sql, parameters = self._prepare(plan)
        connection = self._connect()
        outcome = {"timeout": False}

        def interrupt() -> None:
            connection.interrupt()

        def on_timeout() -> None:
            outcome["timeout"] = True
            interrupt()

        timer = threading.Timer(limits.timeout_seconds, on_timeout)
        started = time.perf_counter()
        try:
            cost = _total_cardinality(
                json.loads(connection.execute(f"EXPLAIN (FORMAT JSON) {sql}", parameters).fetchall()[0][1])
            )
            if cost > limits.max_cost_units:
                raise CostLimitExceeded("estimated cost exceeds the execution limit")
            if cancellation:
                cancellation.bind(interrupt)
                if cancellation.cancelled:  # an interrupt before the statement starts is dropped
                    raise ExecutionCancelled("query was cancelled")
            timer.start()
            cursor = connection.execute(sql, parameters)
            columns = tuple(column[0] for column in cursor.description)
            accumulator = ResultAccumulator(limits)
            while True:
                batch = cursor.fetchmany(1024)
                if not batch:
                    break
                if not all(accumulator.add(tuple(row)) for row in batch):
                    break
        except ExecutionError:
            raise
        except duckdb.InterruptException as exc:
            if outcome["timeout"]:
                raise ExecutionTimeout("query exceeded the execution timeout") from exc
            raise ExecutionCancelled("query was cancelled") from exc
        except duckdb.Error as exc:
            raise ExecutionError(f"query failed: {type(exc).__name__}") from exc
        finally:
            timer.cancel()
            if cancellation:
                cancellation.unbind()
            connection.close()
        return ExecutionResult(
            dialect=self.dialect,
            columns=columns,
            rows=tuple(accumulator.rows),
            byte_count=accumulator.byte_count,
            truncated=accumulator.truncation_reason is not None,
            truncation_reason=accumulator.truncation_reason,
            estimated_cost_units=cost,
            elapsed_ms=int((time.perf_counter() - started) * 1_000),
        )

    def _prepare(self, plan: Any) -> tuple[str, dict[str, Any]]:
        if getattr(plan, "dialect", None) != self.dialect:
            raise DialectMismatch(f"plan dialect is not {self.dialect}")
        validate_read_only_sql(plan.sql, dialect="duckdb", allowed_tables=self._sources)
        # DuckDB binds named parameters as $name; compiled SQL carries only :pN placeholders.
        sql = _NAMED_PARAMETER.sub(r"$\1", plan.sql)
        return sql, dict(plan.parameters)

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = duckdb.connect(":memory:")
        try:
            for table, path in self._sources.items():
                literal = str(path).replace("'", "''")
                connection.execute(
                    f"CREATE VIEW \"{table}\" AS SELECT * FROM {_READERS[path.suffix.lower()]}('{literal}')"
                )
            allowed = ", ".join("'" + str(path).replace("'", "''") + "'" for path in self._sources.values())
            connection.execute(f"SET allowed_paths=[{allowed}]")
            connection.execute("SET enable_external_access=false")
            connection.execute(f"SET memory_limit='{self._memory_limit}'")
            connection.execute(f"SET threads={int(self._threads)}")
            connection.execute("SET lock_configuration=true")
        except Exception:
            connection.close()
            raise
        return connection


def _total_cardinality(node: Any) -> float:
    if isinstance(node, list):
        return sum(_total_cardinality(item) for item in node)
    own = float((node.get("extra_info") or {}).get("Estimated Cardinality", 0) or 0)
    return own + _total_cardinality(node.get("children") or [])
