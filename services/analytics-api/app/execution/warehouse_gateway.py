"""Read-only gateways for Snowflake and Databricks over an injected, driver-neutral session.

The gateway owns the policy that must not depend on a driver: AST validation against a table allowlist,
a dialect check, bind-marker translation, a cost ceiling, bounded streaming, cancellation, a watchdog and
error mapping that never echoes SQL, values or driver messages. A `WarehouseSession` owns everything
driver-specific (connecting, the statement timeout and read-only role settings, EXPLAIN, cancel). The
real driver sessions are not written here: they need a live warehouse to verify and are packet W8.
"""

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Literal, Protocol

from app.execution.gateway import (
    CancellationToken,
    CostLimitExceeded,
    DialectMismatch,
    ExecutionCancelled,
    ExecutionError,
    ExecutionLimits,
    ExecutionResult,
    ExecutionTimeout,
    QueryRejected,
    ResultAccumulator,
)
from app.execution.validation import validate_read_only_sql

ParamStyle = Literal["named", "pyformat"]
_PLACEHOLDER = re.compile(r"(?<![:\w]):(p\d+)\b")
_FETCH_BATCH = 1024


class WarehouseTimeout(Exception):
    """Raised by a session when the warehouse stopped the statement for exceeding its timeout."""


class WarehouseCancelled(Exception):
    """Raised by a session when the statement was cancelled."""


class RowStream(Protocol):
    columns: tuple[str, ...]

    def fetchmany(self, size: int) -> Sequence[tuple[Any, ...]]: ...

    def close(self) -> None: ...


class WarehouseSession(Protocol):
    """One connection's worth of driver behavior. Credentials belong to a read-only role."""

    def prepare(self, *, timeout_seconds: float) -> None:
        """Apply the server-side statement timeout and any session settings (UTC, read-only)."""

    def explain_cost(self, sql: str, parameters: Mapping[str, Any]) -> float | None:
        """Return an engine cost estimate, or None when the engine cannot give one."""

    def execute(self, sql: str, parameters: Mapping[str, Any]) -> RowStream: ...

    def cancel(self) -> None: ...

    def close(self) -> None: ...


def bind_parameters(sql: str, parameters: Mapping[str, Any], style: ParamStyle) -> tuple[str, dict[str, Any]]:
    """Translate the compiler's `:pN` markers; refuse any mismatch between markers and values."""
    markers = set(_PLACEHOLDER.findall(sql))
    if markers != set(parameters):
        raise QueryRejected("bind parameters do not match the query")
    if style == "named":
        return sql, dict(parameters)
    # pyformat: a literal percent sign in the SQL text must be doubled before markers are inserted.
    return _PLACEHOLDER.sub(lambda match: f"%({match.group(1)})s", sql.replace("%", "%%")), dict(parameters)


class WarehouseGateway:
    dialect: str = ""
    sqlglot_dialect: str = ""
    param_style: ParamStyle = "named"

    def __init__(
        self,
        connect: Callable[[], WarehouseSession],
        *,
        allowed_tables: Iterable[str],
        require_cost_estimate: bool = True,
        watchdog_grace_seconds: float = 1.0,
    ) -> None:
        if not self.dialect:
            raise TypeError("use SnowflakeGateway or DatabricksGateway")
        self._connect = connect
        self._allowed_tables = frozenset(name.lower() for name in allowed_tables)
        if not self._allowed_tables:
            raise ValueError("at least one allowed table is required")
        if watchdog_grace_seconds < 0:
            raise ValueError("watchdog_grace_seconds must not be negative")
        self._require_cost_estimate = require_cost_estimate
        self._grace = watchdog_grace_seconds

    def estimate(self, plan: Any) -> float:
        sql, parameters = self._check(plan)
        session = None
        try:
            session = self._connect()
            session.prepare(timeout_seconds=10.0)
            return self._cost(session, sql, parameters)
        except ExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - an unknown estimate must not execute.
            raise ExecutionError("cost estimate failed") from exc
        finally:
            _close_quietly(session)

    def execute(
        self,
        plan: Any,
        *,
        limits: ExecutionLimits,
        cancellation: CancellationToken | None = None,
    ) -> ExecutionResult:
        sql, parameters = self._check(plan)
        started = time.perf_counter()
        timed_out = threading.Event()
        timer: threading.Timer | None = None
        session: WarehouseSession | None = None
        stream: RowStream | None = None
        try:
            session = self._connect()
            session.prepare(timeout_seconds=limits.timeout_seconds)
            cost = self._cost(session, sql, parameters)
            if cost > limits.max_cost_units:
                raise CostLimitExceeded("estimated cost exceeds the execution limit")
            cancel = _quiet(session.cancel)
            if cancellation:
                cancellation.bind(cancel)
            # The warehouse timeout is the real bound; the watchdog covers a stalled link.
            timer = threading.Timer(limits.timeout_seconds + self._grace, lambda: (timed_out.set(), cancel()))
            timer.start()
            stream = session.execute(sql, parameters)
            columns = tuple(stream.columns)
            accumulator = ResultAccumulator(limits)
            while True:
                batch = stream.fetchmany(_FETCH_BATCH)
                if not batch:
                    break
                if not all(accumulator.add(tuple(row)) for row in batch):
                    break
        except ExecutionError:
            raise
        except WarehouseCancelled as exc:
            if cancellation and cancellation.cancelled and not timed_out.is_set():
                raise ExecutionCancelled("query was cancelled") from exc
            raise ExecutionTimeout("query exceeded the execution timeout") from exc
        except WarehouseTimeout as exc:
            raise ExecutionTimeout("query exceeded the execution timeout") from exc
        except Exception as exc:  # noqa: BLE001 - driver messages can carry SQL or values; report the type only.
            if timed_out.is_set():
                raise ExecutionTimeout("query exceeded the execution timeout") from exc
            raise ExecutionError(f"query failed: {type(exc).__name__}") from exc
        finally:
            if timer:
                timer.cancel()
            if cancellation:
                cancellation.unbind()
            _close_quietly(stream)
            _close_quietly(session)
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

    def _check(self, plan: Any) -> tuple[str, dict[str, Any]]:
        if getattr(plan, "dialect", None) != self.dialect:
            raise DialectMismatch(f"plan dialect is not {self.dialect}")
        validate_read_only_sql(plan.sql, dialect=self.sqlglot_dialect, allowed_tables=self._allowed_tables)
        return bind_parameters(plan.sql, plan.parameters, self.param_style)

    def _cost(self, session: WarehouseSession, sql: str, parameters: Mapping[str, Any]) -> float:
        cost = session.explain_cost(sql, parameters)
        if cost is None:
            if self._require_cost_estimate:
                raise ExecutionError("no cost estimate is available for this query")
            return 0.0
        return float(cost)


class SnowflakeGateway(WarehouseGateway):
    """Snowflake's connector binds `%(name)s` markers client-side by default (unverified here: W8)."""

    dialect = "snowflake"
    sqlglot_dialect = "snowflake"
    param_style: ParamStyle = "pyformat"


class DatabricksGateway(WarehouseGateway):
    """Databricks SQL native named markers; marker syntax and cancel support are unverified until W8."""

    dialect = "databricks"
    sqlglot_dialect = "databricks"
    param_style: ParamStyle = "named"


def _quiet(call: Callable[[], None]) -> Callable[[], None]:
    def run() -> None:
        try:
            call()
        except Exception:  # noqa: BLE001 - cancellation is best effort and runs on another thread.
            pass

    return run


def _close_quietly(resource: Any) -> None:
    if resource is None:
        return
    try:
        resource.close()
    except Exception:  # noqa: BLE001
        pass
