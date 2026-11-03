"""W4/W6: Snowflake and Databricks gateway policy, tested against a scriptable fake session (no driver)."""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest

from app.compiler import DatabricksCompilerAdapter, PostgreSQLCompilerAdapter, SnowflakeCompilerAdapter
from app.compiler.postgres import CompiledQuery
from app.execution import (
    CancellationToken,
    CostLimitExceeded,
    DatabricksGateway,
    DialectMismatch,
    ExecutionCancelled,
    ExecutionError,
    ExecutionLimits,
    ExecutionTimeout,
    QueryRejected,
    SnowflakeGateway,
    WarehouseCancelled,
    WarehouseTimeout,
    bind_parameters,
)
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.analytics_intent import AnalyticalIntent

ROOT = Path(__file__).parent.parent
TARGETS = {
    "snowflake": (SnowflakeGateway, SnowflakeCompilerAdapter, "%(p0)s"),
    "databricks": (DatabricksGateway, DatabricksCompilerAdapter, ":p0"),
}


class FakeStream:
    def __init__(self, columns, rows, on_fetch=None):
        self.columns = tuple(columns)
        self._rows = list(rows)
        self._on_fetch = on_fetch
        self.closed = False

    def fetchmany(self, size):
        if self._on_fetch:
            self._on_fetch()
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, *, rows=(), columns=("dimension_0", "metric_0"), cost=10.0, execute_error=None, on_fetch=None):
        self.rows, self.columns, self.cost = rows, columns, cost
        self.execute_error, self.on_fetch = execute_error, on_fetch
        self.prepared_timeout = None
        self.executed: list[tuple[str, dict]] = []
        self.cancelled = threading.Event()
        self.closed = False
        self.stream: FakeStream | None = None

    def prepare(self, *, timeout_seconds):
        self.prepared_timeout = timeout_seconds

    def explain_cost(self, sql, parameters):
        return self.cost

    def execute(self, sql, parameters):
        self.executed.append((sql, dict(parameters)))
        if self.execute_error:
            raise self.execute_error
        self.stream = FakeStream(self.columns, self.rows, self.on_fetch)
        return self.stream

    def cancel(self):
        self.cancelled.set()

    def close(self):
        self.closed = True


def _plan(dialect):
    document = SemanticRegistry(ROOT / "semantic_registry").get_certified("sales-core", "v1")
    intent = AnalyticalIntent.model_validate(
        json.loads((ROOT / "tests/fixtures/semantic/sales-monthly-intent.json").read_text())
    )
    return TARGETS[dialect][1]().compile(intent, document.contract)


def _gateway(dialect, session, **options):
    sessions = []

    def connect():
        sessions.append(session)
        return session

    gateway = TARGETS[dialect][0](connect, allowed_tables={"sales_orders"}, **options)
    gateway.sessions = sessions
    return gateway


@pytest.mark.parametrize("dialect", TARGETS)
def test_executes_a_compiled_plan_with_translated_markers_and_a_server_timeout(dialect):
    session = FakeSession(rows=[("2024-01-01", 5), ("2024-02-01", 7)])
    gateway = _gateway(dialect, session)

    result = gateway.execute(_plan(dialect), limits=ExecutionLimits(timeout_seconds=7.0))

    assert result.dialect == dialect
    assert result.rows == (("2024-01-01", 5), ("2024-02-01", 7))
    assert result.columns == ("dimension_0", "metric_0")
    assert result.estimated_cost_units == 10.0 and not result.truncated
    assert session.prepared_timeout == 7.0
    sql, parameters = session.executed[0]
    assert TARGETS[dialect][2] in sql and set(parameters) == {"p0", "p1", "p2"}
    assert session.closed and session.stream.closed


@pytest.mark.parametrize("dialect", TARGETS)
def test_a_plan_compiled_for_another_dialect_is_refused_before_any_connection(dialect):
    other = "databricks" if dialect == "snowflake" else "snowflake"
    gateway = _gateway(dialect, FakeSession())

    for plan in (_plan(other), CompiledQuery("SELECT 1", {}, dialect="postgres")):
        with pytest.raises(DialectMismatch):
            gateway.execute(plan, limits=ExecutionLimits())
    assert gateway.sessions == []


@pytest.mark.parametrize("dialect", TARGETS)
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales_orders",
        "INSERT INTO sales_orders VALUES (1)",
        "SELECT 1 FROM other_table",
        "SELECT amount FROM sales_orders; DROP TABLE sales_orders",
        "SELECT amount FROM sales_orders WHERE evil_function(amount) > 1",
        "CREATE TABLE x AS SELECT amount FROM sales_orders",
    ],
)
def test_non_read_only_or_out_of_allowlist_sql_is_rejected_without_connecting(dialect, sql):
    gateway = _gateway(dialect, FakeSession())

    with pytest.raises(QueryRejected):
        gateway.execute(CompiledQuery(sql, {}, dialect=dialect), limits=ExecutionLimits())
    assert gateway.sessions == []


@pytest.mark.parametrize("dialect", TARGETS)
def test_marker_and_parameter_mismatch_is_rejected(dialect):
    gateway = _gateway(dialect, FakeSession())
    plan = _plan(dialect)

    with pytest.raises(QueryRejected):
        gateway.execute(CompiledQuery(plan.sql, {"p0": "paid"}, dialect=dialect), limits=ExecutionLimits())


@pytest.mark.parametrize("dialect", TARGETS)
def test_cost_above_the_ceiling_never_executes(dialect):
    session = FakeSession(cost=5_000.0)

    with pytest.raises(CostLimitExceeded):
        _gateway(dialect, session).execute(_plan(dialect), limits=ExecutionLimits(max_cost_units=100.0))
    assert session.executed == [] and session.closed


@pytest.mark.parametrize("dialect", TARGETS)
def test_a_missing_estimate_fails_closed_unless_explicitly_allowed(dialect):
    with pytest.raises(ExecutionError):
        _gateway(dialect, FakeSession(cost=None)).execute(_plan(dialect), limits=ExecutionLimits())

    session = FakeSession(cost=None, rows=[("a", 1)])
    result = _gateway(dialect, session, require_cost_estimate=False).execute(_plan(dialect), limits=ExecutionLimits())
    assert result.rows == (("a", 1),) and result.estimated_cost_units == 0.0


@pytest.mark.parametrize("dialect", TARGETS)
def test_estimate_returns_the_engine_cost_and_closes_the_session(dialect):
    session = FakeSession(cost=42.5)

    assert _gateway(dialect, session).estimate(_plan(dialect)) == 42.5
    assert session.executed == [] and session.closed


@pytest.mark.parametrize("dialect", TARGETS)
def test_row_and_byte_caps_truncate_and_say_so(dialect):
    rows = [(f"g{index}", index) for index in range(50)]

    by_rows = _gateway(dialect, FakeSession(rows=rows)).execute(_plan(dialect), limits=ExecutionLimits(max_rows=10))
    by_bytes = _gateway(dialect, FakeSession(rows=rows)).execute(_plan(dialect), limits=ExecutionLimits(max_bytes=40))

    assert len(by_rows.rows) == 10 and by_rows.truncated and by_rows.truncation_reason == "max_rows"
    assert by_bytes.truncated and by_bytes.truncation_reason == "max_bytes"


@pytest.mark.parametrize("dialect", TARGETS)
def test_cancellation_interrupts_the_session_and_maps_to_cancelled(dialect):
    token = CancellationToken()
    session = FakeSession(rows=[("a", 1)])

    def block_until_cancelled():
        token.cancel()  # a caller cancelling mid-fetch
        if session.cancelled.wait(2):
            raise WarehouseCancelled()

    session.on_fetch = block_until_cancelled

    with pytest.raises(ExecutionCancelled):
        _gateway(dialect, session).execute(_plan(dialect), limits=ExecutionLimits(), cancellation=token)
    assert session.cancelled.is_set() and session.closed


@pytest.mark.parametrize("dialect", TARGETS)
def test_server_timeout_maps_to_a_timeout_error(dialect):
    session = FakeSession(execute_error=WarehouseTimeout())

    with pytest.raises(ExecutionTimeout):
        _gateway(dialect, session).execute(_plan(dialect), limits=ExecutionLimits())
    assert session.closed


@pytest.mark.parametrize("dialect", TARGETS)
def test_a_stalled_link_is_cancelled_by_the_watchdog(dialect):
    session = FakeSession(rows=[("a", 1)])

    def stall():
        if session.cancelled.wait(3):
            raise RuntimeError("connection reset while running the statement")

    session.on_fetch = stall

    with pytest.raises(ExecutionTimeout):
        _gateway(dialect, session, watchdog_grace_seconds=0.0).execute(
            _plan(dialect), limits=ExecutionLimits(timeout_seconds=0.05)
        )
    assert session.cancelled.is_set()


@pytest.mark.parametrize("dialect", TARGETS)
def test_driver_errors_never_echo_sql_values_or_messages(dialect):
    session = FakeSession(execute_error=RuntimeError("SELECT secret FROM vault WHERE token='abc123'"))

    with pytest.raises(ExecutionError) as caught:
        _gateway(dialect, session).execute(_plan(dialect), limits=ExecutionLimits())

    assert str(caught.value) == "query failed: RuntimeError"
    assert session.closed


def test_a_base_gateway_cannot_be_used_directly():
    from app.execution import WarehouseGateway

    with pytest.raises(TypeError):
        WarehouseGateway(lambda: FakeSession(), allowed_tables={"t"})


@pytest.mark.parametrize("cls", [SnowflakeGateway, DatabricksGateway])
def test_at_least_one_allowed_table_is_required(cls):
    with pytest.raises(ValueError):
        cls(lambda: FakeSession(), allowed_tables=[])


def test_bind_parameters_styles_and_percent_escaping():
    sql = "SELECT 1 FROM t WHERE a = :p0 AND b LIKE '%x' AND c = :p1"
    values = {"p0": 1, "p1": 2}

    assert bind_parameters(sql, values, "named") == (sql, values)
    assert bind_parameters(sql, values, "pyformat") == (
        "SELECT 1 FROM t WHERE a = %(p0)s AND b LIKE '%%x' AND c = %(p1)s",
        values,
    )
    with pytest.raises(QueryRejected):
        bind_parameters(sql, {"p0": 1}, "named")
    with pytest.raises(QueryRejected):
        bind_parameters("SELECT 1", {"p0": 1}, "named")


def test_the_postgres_compiler_plan_is_not_accepted_by_a_warehouse_gateway():
    document = SemanticRegistry(ROOT / "semantic_registry").get_certified("sales-core", "v1")
    intent = AnalyticalIntent.model_validate(
        json.loads((ROOT / "tests/fixtures/semantic/sales-monthly-intent.json").read_text())
    )
    plan = PostgreSQLCompilerAdapter().compile(intent, document.contract)

    with pytest.raises(DialectMismatch):
        _gateway("snowflake", FakeSession()).execute(plan, limits=ExecutionLimits())
