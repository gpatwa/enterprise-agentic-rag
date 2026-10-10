"""PostgreSQL read-only gateway over an injected SQLAlchemy engine."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterable
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

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

_QUERY_CANCELED = "57014"


class PostgresGateway:
    """Run validated compiled queries in a read-only transaction with server-side limits.

    The caller supplies the engine (and so the credentials, which should belong to a
    read-only role); this class adds defense in depth: AST validation, a table
    allowlist, `SET TRANSACTION READ ONLY`, `statement_timeout`, a planner cost
    ceiling checked with EXPLAIN before running, bounded streaming, and cancellation
    through the driver's cancel call. The transaction is always rolled back.
    """

    dialect = "postgres"

    def __init__(self, engine: Any, *, allowed_tables: Iterable[str]) -> None:
        self._engine = engine
        self._allowed_tables = frozenset(name.lower() for name in allowed_tables)
        if not self._allowed_tables:
            raise ValueError("at least one allowed table is required")

    def estimate(self, plan: Any) -> float:
        self._check(plan)
        try:
            with self._engine.connect() as connection:
                self._begin_read_only(connection, timeout_seconds=10.0)
                try:
                    return self._explain_cost(connection, plan)
                finally:
                    connection.rollback()
        except ExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - an unknown estimate must not execute.
            raise ExecutionError("cost estimate failed") from exc

    def execute(
        self,
        plan: Any,
        *,
        limits: ExecutionLimits,
        cancellation: CancellationToken | None = None,
    ) -> ExecutionResult:
        self._check(plan)
        started = time.perf_counter()
        timed_out = threading.Event()
        timer: threading.Timer | None = None
        try:
            with self._engine.connect() as connection:
                try:
                    self._begin_read_only(connection, timeout_seconds=limits.timeout_seconds)
                    cost = self._explain_cost(connection, plan)
                    if cost > limits.max_cost_units:
                        raise CostLimitExceeded("estimated cost exceeds the execution limit")
                    cancel = _cancel_hook(connection)
                    if cancellation:
                        cancellation.bind(cancel)
                    # statement_timeout is the server-side bound; the timer covers a stalled link.
                    timer = threading.Timer(limits.timeout_seconds + 1.0, lambda: (timed_out.set(), cancel()))
                    timer.start()
                    result = connection.execution_options(stream_results=True).execute(
                        text(plan.sql), dict(plan.parameters)
                    )
                    columns = tuple(result.keys())
                    accumulator = ResultAccumulator(limits)
                    while True:
                        batch = result.fetchmany(1024)
                        if not batch:
                            break
                        if not all(accumulator.add(tuple(row)) for row in batch):
                            break
                    result.close()
                finally:
                    if timer:
                        timer.cancel()
                    if cancellation:
                        cancellation.unbind()
                    connection.rollback()
        except ExecutionError:
            raise
        except DBAPIError as exc:
            if _is_cancel(exc):
                if cancellation and cancellation.cancelled and not timed_out.is_set():
                    raise ExecutionCancelled("query was cancelled") from exc
                raise ExecutionTimeout("query exceeded the execution timeout") from exc
            raise ExecutionError(f"query failed: {type(exc.orig).__name__}") from exc
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

    def _check(self, plan: Any) -> None:
        if getattr(plan, "dialect", None) != self.dialect:
            raise DialectMismatch(f"plan dialect is not {self.dialect}")
        validate_read_only_sql(plan.sql, dialect="postgres", allowed_tables=self._allowed_tables)

    @staticmethod
    def _begin_read_only(connection: Any, *, timeout_seconds: float) -> None:
        # Must be the first statements of the transaction; SET LOCAL ends with it.
        connection.exec_driver_sql("SET TRANSACTION READ ONLY")
        millis = max(1, int(timeout_seconds * 1_000))
        connection.exec_driver_sql(f"SET LOCAL statement_timeout = {millis}")
        connection.exec_driver_sql(f"SET LOCAL lock_timeout = {millis}")

    @staticmethod
    def _explain_cost(connection: Any, plan: Any) -> float:
        row = connection.execute(text(f"EXPLAIN (FORMAT JSON) {plan.sql}"), dict(plan.parameters)).fetchone()
        document = row[0]
        if isinstance(document, str):
            document = json.loads(document)
        return float(document[0]["Plan"]["Total Cost"])


def _cancel_hook(connection: Any):
    def cancel() -> None:
        raw = connection.connection.driver_connection
        raw.cancel()

    return cancel


def _is_cancel(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "pgcode", None) == _QUERY_CANCELED
