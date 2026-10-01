"""ADS-040: dialect, file isolation, timeout, cancellation, row/byte/cost limits."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import duckdb
import pytest
from sqlalchemy.exc import DBAPIError

from app.compiler import DuckDBCompilerAdapter, PostgreSQLCompilerAdapter
from app.compiler.postgres import CompiledQuery
from app.execution import (
    CancellationToken,
    CostLimitExceeded,
    DialectMismatch,
    DuckDBGateway,
    ExecutionCancelled,
    ExecutionError,
    ExecutionLimits,
    ExecutionResultStore,
    ExecutionTimeout,
    GatewayCostEstimator,
    GatewayExecutor,
    PostgresGateway,
    QueryRejected,
    validate_read_only_sql,
)
from app.runtime.governed_stages import CompiledPlanStore, fake_execution_node
from packages.platform_contracts.agent_runtime import NodeInput, RunBudget
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract


def _contract() -> SemanticContract:
    return SemanticContract.model_validate(
        {
            "id": "sales-core",
            "tenant_id": "tenant-a",
            "domain": "sales",
            "version": "v1",
            "owners": [{"id": "team.data", "display_name": "Data", "owner_type": "team"}],
            "datasets": [
                {
                    "id": "orders",
                    "display_name": "Orders",
                    "source_asset_id": "warehouse.orders",
                    "physical_name": "sales_orders",
                    "description": "One row per order",
                    "owner_ids": ["team.data"],
                }
            ],
            "fields": [
                {"id": "orders.id", "dataset_id": "orders", "physical_name": "id", "data_type": "string"},
                {"id": "orders.amount", "dataset_id": "orders", "physical_name": "amount", "data_type": "decimal"},
                {"id": "orders.status", "dataset_id": "orders", "physical_name": "status", "data_type": "string"},
                {
                    "id": "orders.created_at",
                    "dataset_id": "orders",
                    "physical_name": "created_at",
                    "data_type": "timestamp",
                },
            ],
            "dimensions": [
                {
                    "id": "status",
                    "dataset_id": "orders",
                    "field_id": "orders.status",
                    "dimension_type": "categorical",
                    "owner_ids": ["team.data"],
                },
                {
                    "id": "created_at",
                    "dataset_id": "orders",
                    "field_id": "orders.created_at",
                    "dimension_type": "temporal",
                    "owner_ids": ["team.data"],
                },
            ],
            "metrics": [
                {
                    "id": "revenue",
                    "dataset_id": "orders",
                    "aggregation": "sum",
                    "measure_field_id": "orders.amount",
                    "grain": {"kind": "order", "key_field_ids": ["orders.id"]},
                    "certification": "certified",
                    "owner_ids": ["team.data"],
                }
            ],
        }
    )


def _intent(**overrides) -> AnalyticalIntent:
    values = {
        "query_id": "q-1",
        "tenant_id": "tenant-a",
        "dataset_id": "orders",
        "semantic_contract": {"contract_id": "sales-core", "contract_version": "v1"},
        "metrics": [{"metric_id": "revenue"}],
        "group_by": [{"dimension_id": "status"}],
        "filters": [{"field_id": "orders.status", "operator": "in", "values": ["paid", "refunded"]}],
        "time_range": {"dimension_id": "created_at", "start": "2024-01-01T00:00:00", "end": "2024-12-31T00:00:00"},
        "sort": [{"target_kind": "metric", "target_id": "revenue", "direction": "desc"}],
        "limit": 25,
    }
    values.update(overrides)
    return AnalyticalIntent.model_validate(values)


@pytest.fixture
def lake(tmp_path):
    root = tmp_path / "lake"
    root.mkdir()
    connection = duckdb.connect()
    connection.execute("""
        CREATE TABLE sales_orders AS
        SELECT 'o' || i AS id,
               CAST(i AS DECIMAL(12,2)) AS amount,
               CASE WHEN i % 4 = 0 THEN 'refunded' WHEN i % 4 = 3 THEN 'cancelled' ELSE 'paid' END AS status,
               TIMESTAMP '2024-01-01' + INTERVAL (i) HOUR AS created_at
        FROM range(1, 401) t(i)
    """)
    connection.execute(f"COPY sales_orders TO '{root / 'sales_orders.parquet'}' (FORMAT PARQUET)")
    connection.execute(f"COPY (SELECT 'secret' AS token) TO '{root / 'secret.csv'}' (FORMAT CSV, HEADER)")
    outside = tmp_path / "outside.parquet"
    connection.execute(f"COPY sales_orders TO '{outside}' (FORMAT PARQUET)")
    connection.close()
    return SimpleNamespace(root=root, orders=root / "sales_orders.parquet", outside=outside)


@pytest.fixture
def gateway(lake):
    return DuckDBGateway({"sales_orders": lake.orders}, allowed_root=lake.root)


def _plan(sql: str, dialect: str = "duckdb", parameters: dict | None = None) -> CompiledQuery:
    return CompiledQuery(sql=sql, parameters=parameters or {}, dialect=dialect)


def test_compilers_tag_plans_with_their_dialect():
    assert PostgreSQLCompilerAdapter().compile(_intent(), _contract()).dialect == "postgres"
    assert DuckDBCompilerAdapter().compile(_intent(), _contract()).dialect == "duckdb"


def test_duckdb_runs_compiled_intent_and_matches_independent_aggregation(gateway, lake):
    plan = DuckDBCompilerAdapter().compile(_intent(), _contract())
    result = gateway.execute(plan, limits=ExecutionLimits())
    expected = (
        duckdb.connect()
        .execute(
            f"""SELECT status, SUM(amount) FROM read_parquet('{lake.orders}')
        WHERE status IN ('paid','refunded') AND created_at >= TIMESTAMP '2024-01-01'
          AND created_at <= TIMESTAMP '2024-12-31' GROUP BY 1 ORDER BY 2 DESC"""
        )
        .fetchall()
    )
    assert result.dialect == "duckdb" and not result.truncated
    assert [tuple(row) for row in result.rows] == [tuple(row) for row in expected]
    assert result.columns == ("dimension_0", "metric_0")
    assert result.estimated_cost_units > 0 and result.byte_count > 0


def test_plan_for_another_dialect_is_refused_before_any_connection(gateway):
    with pytest.raises(DialectMismatch):
        gateway.execute(_plan("SELECT 1 FROM sales_orders", dialect="postgres"), limits=ExecutionLimits())
    with pytest.raises(DialectMismatch):
        gateway.estimate(_plan("SELECT 1 FROM sales_orders", dialect="postgres"))


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales_orders",
        "DROP TABLE sales_orders",
        "INSERT INTO sales_orders VALUES (1)",
        "SELECT 1 FROM sales_orders; SELECT 2 FROM sales_orders",
        "COPY sales_orders TO 'x.csv'",
        "ATTACH 'x.db'",
        "SET enable_external_access=true",
        "SELECT * FROM read_csv_auto('secret.csv')",
        "SELECT * FROM read_parquet('secret.parquet')",
        "SELECT * FROM other_table",
        "SELECT * FROM main.sales_orders",
        "SELECT pg_sleep(100) FROM sales_orders",
        "SELECT * FROM sales_orders INTO OUTFILE 'x'",
    ],
)
def test_unsafe_sql_is_rejected(gateway, sql):
    with pytest.raises(QueryRejected):
        gateway.execute(_plan(sql), limits=ExecutionLimits())


def test_validator_allows_cte_and_subquery_over_allowlisted_tables():
    validate_read_only_sql(
        "WITH t AS (SELECT status, SUM(amount) AS s FROM sales_orders GROUP BY 1) "
        "SELECT * FROM t WHERE s > (SELECT AVG(amount) FROM sales_orders)",
        dialect="duckdb",
        allowed_tables=["sales_orders"],
    )


def test_gateway_construction_confines_sources_to_allowed_root(lake):
    with pytest.raises(PermissionError):
        DuckDBGateway({"sales_orders": lake.outside}, allowed_root=lake.root)
    with pytest.raises(PermissionError):
        DuckDBGateway({"sales_orders": lake.root / ".." / "outside.parquet"}, allowed_root=lake.root)
    with pytest.raises(ValueError):
        DuckDBGateway({"bad name": lake.orders}, allowed_root=lake.root)
    with pytest.raises(FileNotFoundError):
        DuckDBGateway({"missing": lake.root / "missing.parquet"}, allowed_root=lake.root)


def test_engine_level_isolation_holds_even_if_validation_were_bypassed(gateway, lake):
    """Defense in depth: the locked connection itself refuses files outside the allowlist."""
    connection = gateway._connect()
    try:
        for sql in (
            f"SELECT * FROM read_parquet('{lake.outside}')",
            f"SELECT * FROM read_csv_auto('{lake.root / 'secret.csv'}')",
            "SET enable_external_access=true",
            "ATTACH 'x.db'",
            f"COPY sales_orders TO '{lake.root / 'leak.csv'}'",
        ):
            with pytest.raises(duckdb.Error):
                connection.execute(sql)
        assert not (lake.root / "leak.csv").exists()
        assert connection.execute("SELECT COUNT(*) FROM sales_orders").fetchone() == (400,)
    finally:
        connection.close()


def test_row_limit_truncates_and_reports_reason(gateway):
    result = gateway.execute(_plan("SELECT id FROM sales_orders ORDER BY id"), limits=ExecutionLimits(max_rows=7))
    assert result.row_count == 7 and result.truncated and result.truncation_reason == "max_rows"


def test_byte_limit_truncates_and_reports_reason(gateway):
    result = gateway.execute(_plan("SELECT id FROM sales_orders ORDER BY id"), limits=ExecutionLimits(max_bytes=40))
    assert result.truncated and result.truncation_reason == "max_bytes"
    assert result.byte_count <= 40 and 0 < result.row_count < 400


def test_exact_fit_is_not_reported_as_truncation(gateway):
    result = gateway.execute(_plan("SELECT id FROM sales_orders"), limits=ExecutionLimits(max_rows=400))
    assert result.row_count == 400 and not result.truncated


def test_cost_limit_blocks_before_execution(gateway):
    plan = _plan("SELECT a.id FROM sales_orders a CROSS JOIN sales_orders b")
    assert gateway.estimate(plan) > 1_000
    with pytest.raises(CostLimitExceeded):
        gateway.execute(plan, limits=ExecutionLimits(max_cost_units=1_000))


def test_timeout_interrupts_long_running_query(gateway):
    plan = _plan("SELECT COUNT(*) FROM sales_orders a, sales_orders b, sales_orders c, sales_orders d, sales_orders e")
    started = time.perf_counter()
    with pytest.raises(ExecutionTimeout):
        gateway.execute(plan, limits=ExecutionLimits(timeout_seconds=0.3, max_cost_units=1e18))
    assert time.perf_counter() - started < 10


def test_cancellation_interrupts_running_query_and_is_not_a_timeout(gateway):
    plan = _plan("SELECT COUNT(*) FROM sales_orders a, sales_orders b, sales_orders c, sales_orders d, sales_orders e")
    token = CancellationToken()
    threading.Timer(0.3, token.cancel).start()
    with pytest.raises(ExecutionCancelled):
        gateway.execute(plan, limits=ExecutionLimits(timeout_seconds=60, max_cost_units=1e18), cancellation=token)


def test_pre_cancelled_token_stops_the_query(gateway):
    token = CancellationToken()
    token.cancel()
    plan = _plan("SELECT COUNT(*) FROM sales_orders a, sales_orders b, sales_orders c, sales_orders d, sales_orders e")
    with pytest.raises(ExecutionCancelled):
        gateway.execute(plan, limits=ExecutionLimits(timeout_seconds=60, max_cost_units=1e18), cancellation=token)


def test_driver_errors_do_not_leak_sql_or_values(gateway):
    with pytest.raises(ExecutionError) as caught:
        gateway.execute(_plan("SELECT CAST(status AS INTEGER) FROM sales_orders"), limits=ExecutionLimits())
    assert "status" not in str(caught.value) and "paid" not in str(caught.value)


def test_limits_must_be_positive():
    with pytest.raises(ValueError):
        ExecutionLimits(max_rows=0)


# ---- PostgreSQL gateway against a recording fake engine (no live database) ----


class _PgError(Exception):
    def __init__(self, pgcode: str | None):
        super().__init__("db error")
        self.pgcode = pgcode


class _FakeResult:
    def __init__(self, columns, rows, fail=None):
        self._columns, self._rows, self._fail = columns, list(rows), fail

    def keys(self):
        return self._columns

    def fetchmany(self, size):
        if self._fail:
            raise self._fail
        batch, self._rows = self._rows[:size], self._rows[size:]
        return batch

    def fetchone(self):
        return self._rows[0]

    def close(self):
        pass


class _FakeConnection:
    def __init__(self, script):
        self.script = script
        self.statements: list[str] = []
        self.options: list[dict] = []
        self.rolled_back = 0
        self.cancels = 0
        self.connection = SimpleNamespace(driver_connection=SimpleNamespace(cancel=self._cancel))

    def _cancel(self):
        self.cancels += 1

    def exec_driver_sql(self, statement):
        self.statements.append(statement)

    def execution_options(self, **options):
        self.options.append(options)
        return self

    def execute(self, clause, parameters=None):
        sql = str(clause)
        self.statements.append(sql)
        if sql.startswith("EXPLAIN"):
            return _FakeResult(["QUERY PLAN"], [([{"Plan": {"Total Cost": self.script["cost"]}}],)])
        if self.script.get("block"):
            self.script["block"].wait(5)
        return _FakeResult(["dimension_0", "metric_0"], self.script["rows"], self.script.get("fail"))

    def rollback(self):
        self.rolled_back += 1

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeEngine:
    def __init__(self, **script):
        self.script = {"cost": 10.0, "rows": [("paid", 1), ("refunded", 2)], **script}
        self.connections: list[_FakeConnection] = []

    def connect(self):
        connection = _FakeConnection(self.script)
        self.connections.append(connection)
        return connection


def _pg_plan(sql='SELECT status AS dimension_0, SUM(amount) AS metric_0 FROM "sales_orders" AS d0 GROUP BY 1'):
    return _plan(sql, dialect="postgres", parameters={"p0": 1})


def test_postgres_runs_in_read_only_transaction_with_timeouts_and_always_rolls_back():
    engine = _FakeEngine()
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    result = gateway.execute(_pg_plan(), limits=ExecutionLimits(timeout_seconds=2))
    connection = engine.connections[0]
    assert connection.statements[:3] == [
        "SET TRANSACTION READ ONLY",
        "SET LOCAL statement_timeout = 2000",
        "SET LOCAL lock_timeout = 2000",
    ]
    assert connection.options == [{"stream_results": True}]
    assert connection.rolled_back == 1
    assert result.rows == (("paid", 1), ("refunded", 2)) and result.estimated_cost_units == 10.0


def test_postgres_cost_limit_blocks_before_running_the_query():
    engine = _FakeEngine(cost=5_000.0)
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    with pytest.raises(CostLimitExceeded):
        gateway.execute(_pg_plan(), limits=ExecutionLimits(max_cost_units=100))
    connection = engine.connections[0]
    assert not connection.options and connection.rolled_back == 1
    assert gateway.estimate(_pg_plan()) == 5_000.0


def test_postgres_row_limit_truncates():
    engine = _FakeEngine(rows=[("a", i) for i in range(50)])
    result = PostgresGateway(engine, allowed_tables=["sales_orders"]).execute(
        _pg_plan(), limits=ExecutionLimits(max_rows=10)
    )
    assert result.row_count == 10 and result.truncation_reason == "max_rows"


def test_postgres_server_cancel_is_timeout_unless_caller_cancelled():
    failure = DBAPIError("stmt", {}, _PgError("57014"))
    gateway = PostgresGateway(_FakeEngine(fail=failure), allowed_tables=["sales_orders"])
    with pytest.raises(ExecutionTimeout):
        gateway.execute(_pg_plan(), limits=ExecutionLimits())
    token = CancellationToken()
    token.cancel()
    with pytest.raises(ExecutionCancelled):
        gateway.execute(_pg_plan(), limits=ExecutionLimits(), cancellation=token)


def test_postgres_other_driver_errors_are_opaque():
    failure = DBAPIError("SELECT secret FROM x", {"p0": "pii"}, _PgError("42703"))
    gateway = PostgresGateway(_FakeEngine(fail=failure), allowed_tables=["sales_orders"])
    with pytest.raises(ExecutionError) as caught:
        gateway.execute(_pg_plan(), limits=ExecutionLimits())
    assert "secret" not in str(caught.value) and "pii" not in str(caught.value)


def test_postgres_cancellation_invokes_driver_cancel_while_query_runs():
    block = threading.Event()
    engine = _FakeEngine(block=block)
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    token = CancellationToken()

    def cancel_then_release():
        time.sleep(0.2)
        token.cancel()
        block.set()

    threading.Thread(target=cancel_then_release).start()
    gateway.execute(_pg_plan(), limits=ExecutionLimits(), cancellation=token)
    assert engine.connections[0].cancels == 1


def test_postgres_rejects_unsafe_sql_and_wrong_dialect_without_connecting():
    engine = _FakeEngine()
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    for sql in ("DROP TABLE sales_orders", "SELECT * FROM pg_catalog.pg_user", "SELECT pg_sleep(9) FROM sales_orders"):
        with pytest.raises(QueryRejected):
            gateway.execute(_pg_plan(sql), limits=ExecutionLimits())
    with pytest.raises(DialectMismatch):
        gateway.execute(_plan("SELECT 1 FROM sales_orders", dialect="duckdb"), limits=ExecutionLimits())
    assert engine.connections == []
    with pytest.raises(ValueError):
        PostgresGateway(engine, allowed_tables=[])


def test_compiled_postgres_plan_passes_gateway_validation():
    plan = PostgreSQLCompilerAdapter().compile(_intent(), _contract())
    validate_read_only_sql(plan.sql, dialect="postgres", allowed_tables=["sales_orders"])


# ---- graph bridge ----


def test_graph_execution_node_runs_through_gateway_bridge(gateway):
    plans = CompiledPlanStore()
    plan = DuckDBCompilerAdapter().compile(_intent(), _contract())
    reference = plans.put("tenant-a", "run-1", plan)
    results = ExecutionResultStore()
    gateways = {"duckdb": gateway}
    executor = GatewayExecutor(plans, gateways, results, ExecutionLimits())
    node_input = NodeInput(
        run_id="run-1",
        tenant_id="tenant-a",
        purpose="analysis",
        node_id="execute",
        state_version=1,
        context_snapshot_id="snap-1",
        payload={"compiled_plan_reference": reference},
        remaining_budget=RunBudget(deadline=datetime.now(timezone.utc) + timedelta(minutes=5)),
    )
    output = fake_execution_node(executor)(node_input)
    assert output.status == "completed" and output.next_node == "result_validate"
    stored = results.get("tenant-a", "run-1", output.payload["execution_reference"])
    assert stored.row_count == 2
    with pytest.raises(LookupError):
        results.get("tenant-b", "run-1", output.payload["execution_reference"])
    assert GatewayCostEstimator(gateways).estimate(plan) > 0
    with pytest.raises(LookupError):
        GatewayCostEstimator({}).estimate(plan)
