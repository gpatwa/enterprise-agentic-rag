"""ADS-040: the PostgreSQL gateway and compiler output against a real PostgreSQL server.

Skipped unless ANALYTICS_TEST_POSTGRES_URL points at a disposable PostgreSQL server (a superuser URL; the module creates
its own database and a read-only login role, and drops both at the end), so unit CI never needs a server. All data is
synthetic and generated here; expected values are computed in Python, not by the server under test.

The server must enforce password authentication (not `trust`): the wrong-password test needs a real rejection.
"""

from __future__ import annotations

import os
import secrets
import threading
import time
import uuid
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url

from app.compiler import PostgreSQLCompiler, PostgreSQLCompilerAdapter
from app.compiler.postgres import CompiledQuery
from app.execution import (
    CancellationToken,
    CostLimitExceeded,
    ExecutionCancelled,
    ExecutionError,
    ExecutionLimits,
    ExecutionTimeout,
    GatewayCostEstimator,
    PostgresGateway,
    QueryRejected,
)
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract

ADMIN_URL = os.environ.get("ANALYTICS_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not ADMIN_URL, reason="needs ANALYTICS_TEST_POSTGRES_URL (a disposable PostgreSQL server)"
)

ORDER_COUNT = 400
EVENT_COUNT = 30_000
# A cross join of the event table with itself: far too slow for a 1 second timeout, and it holds no write lock.
SLOW_SQL = "SELECT COUNT(*) AS n FROM sales_events AS a CROSS JOIN sales_events AS b"
HUGE_COST = ExecutionLimits(max_cost_units=1e15)


def _order(i: int) -> dict:
    return {
        "id": f"o{i}",
        "amount": None if i % 40 == 0 else Decimal(i * 125) / 100,  # 1.25 per step, a NULL every 40th row
        "status": None if i % 37 == 0 else "refunded" if i % 4 == 0 else "cancelled" if i % 4 == 3 else "paid",
        "created_at": datetime(2024, 1, 1) + timedelta(hours=i),
        "customer_id": f"c{i % 25}",
    }


ORDERS = [_order(i) for i in range(1, ORDER_COUNT + 1)]


@pytest.fixture(scope="module")
def server():
    """A throwaway database with synthetic tables and a login role that may only SELECT two of them."""
    suffix = uuid.uuid4().hex[:10]
    database, role, password = f"ads040_{suffix}", f"ads040_ro_{suffix}", secrets.token_hex(16)
    admin = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{database}"'))
        connection.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
    owner_url = make_url(ADMIN_URL).set(database=database)
    owner = create_engine(owner_url)
    with owner.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE sales_orders (id text PRIMARY KEY, amount numeric(12,2), status text,"
                " created_at timestamp, customer_id text)"
            )
        )
        connection.execute(
            text("INSERT INTO sales_orders VALUES (:id, :amount, :status, :created_at, :customer_id)"), ORDERS
        )
        connection.execute(
            text("CREATE TABLE sales_events AS SELECT g AS id FROM generate_series(1, :n) AS g"), {"n": EVENT_COUNT}
        )
        # A table whose name differs from the allowlisted one only by case, and one (write_audit) the role may not read at all.
        connection.execute(text('CREATE TABLE "Sales_Orders" (id text, status text)'))
        connection.execute(text("INSERT INTO \"Sales_Orders\" VALUES ('decoy', 'secret')"))
        connection.execute(text("CREATE TABLE write_audit (n int)"))
        connection.execute(text("CREATE SEQUENCE audit_seq"))
        connection.execute(
            text(
                "CREATE FUNCTION write_probe() RETURNS int LANGUAGE sql VOLATILE AS 'INSERT INTO write_audit VALUES (1) RETURNING n'"
            )
        )
        # Names that need quoting: spaces, upper case, an embedded double quote and a reserved word.
        connection.execute(
            text(
                'CREATE TABLE "Order Items" ("Line Total" numeric(10,2), "Ship ""Mode""" text, "select" text, "Ordered At" timestamp)'
            )
        )
        connection.execute(
            text(
                "INSERT INTO \"Order Items\" VALUES (10.50, 'air', 'a', '2024-03-05 10:00'), (4.25, 'sea', 'a', '2024-03-20 11:00'), (7.00, 'air', 'b', '2024-04-02 09:00')"
            )
        )
        connection.execute(text(f'GRANT CONNECT ON DATABASE "{database}" TO "{role}"'))
        # The decoy is readable on purpose: only the gateway's allowlist, not a missing privilege, may keep it out of reach.
        connection.execute(
            text(f'GRANT SELECT ON sales_orders, sales_events, "Order Items", "Sales_Orders" TO "{role}"')
        )
    yield {
        "owner_url": owner_url,
        "ro_url": owner_url.set(username=role, password=password),
        "password": password,
        "database": database,
    }
    owner.dispose()
    with admin.connect() as connection:
        connection.execute(text(f'DROP DATABASE "{database}" WITH (FORCE)'))
        connection.execute(text(f'DROP ROLE "{role}"'))
    admin.dispose()


@pytest.fixture
def engine(server):
    engine = create_engine(server["ro_url"], pool_size=2, max_overflow=0, pool_timeout=3)
    yield engine
    engine.dispose()


@pytest.fixture
def owner_engine(server):
    engine = create_engine(server["owner_url"])
    yield engine
    engine.dispose()


@pytest.fixture
def gateway(engine):
    return PostgresGateway(engine, allowed_tables=["sales_orders", "sales_events", "Order Items"])


def _plan(sql: str, **parameters) -> CompiledQuery:
    return CompiledQuery(sql=sql, parameters=parameters, dialect="postgres")


def _scalar(engine, sql: str):
    with engine.connect() as connection:
        return connection.execute(text(sql)).scalar()


# ---- the compiler's PostgreSQL output on a real server ----


def _field(identifier: str, dataset: str, physical: str, data_type: str) -> dict:
    return {"id": identifier, "dataset_id": dataset, "physical_name": physical, "data_type": data_type}


def _metric(identifier: str, aggregation: str, measure: str | None, key: str = "orders.id") -> dict:
    metric = {
        "id": identifier,
        "dataset_id": "orders",
        "aggregation": aggregation,
        "grain": {"kind": "order", "key_field_ids": [key]},
        "certification": "certified",
        "owner_ids": ["team.data"],
    }
    if measure:
        metric["measure_field_id"] = measure
    return metric


def _dimension(identifier: str, field: str, kind: str) -> dict:
    return {
        "id": identifier,
        "dataset_id": "orders",
        "field_id": field,
        "dimension_type": kind,
        "owner_ids": ["team.data"],
    }


@pytest.fixture(scope="module")
def contract() -> SemanticContract:
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
                _field("orders.id", "orders", "id", "string"),
                _field("orders.amount", "orders", "amount", "decimal"),
                _field("orders.status", "orders", "status", "string"),
                _field("orders.created_at", "orders", "created_at", "timestamp"),
                _field("orders.customer_id", "orders", "customer_id", "string"),
            ],
            "dimensions": [
                _dimension("status", "orders.status", "categorical"),
                _dimension("created_at", "orders.created_at", "temporal"),
                _dimension("customer", "orders.customer_id", "categorical"),
            ],
            "metrics": [
                _metric("revenue", "sum", "orders.amount"),
                _metric("order_count", "count", None),
                _metric("avg_amount", "average", "orders.amount"),
                _metric("min_amount", "min", "orders.amount"),
                _metric("max_amount", "max", "orders.amount"),
                _metric("customers", "count_distinct", "orders.customer_id"),
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
        "limit": 100,
    }
    values.update(overrides)
    return AnalyticalIntent.model_validate(values)


def _run(gateway, contract, intent, *, compiler=None, limits=None):
    plan = (compiler or PostgreSQLCompilerAdapter()).compile(intent, contract)
    return plan, gateway.execute(plan, limits=limits or ExecutionLimits())


def _expected(rows, key=lambda r: r["status"]):
    groups: dict = {}
    for row in rows:
        groups.setdefault(key(row), []).append(row)
    return groups


def _sum(rows):
    values = [r["amount"] for r in rows if r["amount"] is not None]
    return sum(values, Decimal(0)) if values else None


def test_grouped_aggregates_match_an_independent_python_computation(gateway, contract):
    intent = _intent(
        metrics=[
            {"metric_id": m} for m in ("revenue", "order_count", "avg_amount", "min_amount", "max_amount", "customers")
        ],
        group_by=[{"dimension_id": "status"}],
        sort=[{"target_kind": "dimension", "target_id": "status", "direction": "asc"}],
    )
    _, result = _run(gateway, contract, intent)
    assert result.columns == (
        "dimension_0",
        "metric_0",
        "metric_1",
        "metric_2",
        "metric_3",
        "metric_4",
        "metric_5",
    )
    groups = _expected(ORDERS)
    assert {row[0] for row in result.rows} == set(groups)  # includes the NULL status group
    for status, count, avg, low, high, customers in (
        (row[0], row[2], row[3], row[4], row[5], row[6]) for row in result.rows
    ):
        rows = groups[status]
        amounts = [r["amount"] for r in rows if r["amount"] is not None]
        assert count == len(rows)  # COUNT(*) counts rows whose amount is NULL too
        assert low == min(amounts) and high == max(amounts)
        assert abs(avg - sum(amounts) / len(amounts)) < Decimal("1e-9")  # numeric AVG is exact to many places
        assert customers == len({r["customer_id"] for r in rows})
    revenue = {row[0]: row[1] for row in result.rows}
    assert {status: revenue[status] for status in groups} == {status: _sum(rows) for status, rows in groups.items()}
    assert all(isinstance(row[1], Decimal) for row in result.rows)  # numeric stays exact, never float


def test_ungrouped_total_matches_and_null_amounts_are_skipped_by_sum(gateway, contract):
    _, result = _run(gateway, contract, _intent())
    assert result.rows == ((_sum(ORDERS),),)
    assert result.columns == ("metric_0",)


def test_filters_in_not_in_comparison_and_equality_bind_correctly(gateway, contract):
    cases = [
        (
            {"field_id": "orders.status", "operator": "in", "values": ["paid", "refunded"]},
            lambda r: r["status"] in ("paid", "refunded"),
        ),
        (
            {"field_id": "orders.status", "operator": "not_in", "values": ["paid"]},
            lambda r: r["status"] is not None and r["status"] != "paid",
        ),
        (
            {"field_id": "orders.status", "operator": "equals", "values": ["cancelled"]},
            lambda r: r["status"] == "cancelled",
        ),
        (
            {"field_id": "orders.status", "operator": "not_equals", "values": ["paid"]},
            lambda r: r["status"] is not None and r["status"] != "paid",
        ),
        (
            {"field_id": "orders.amount", "operator": "greater_than", "values": [300]},
            lambda r: r["amount"] is not None and r["amount"] > 300,
        ),
        (
            {"field_id": "orders.amount", "operator": "less_than_or_equal", "values": [1.25]},
            lambda r: r["amount"] is not None and r["amount"] <= Decimal("1.25"),
        ),
    ]
    for filter_, predicate in cases:
        _, result = _run(gateway, contract, _intent(metrics=[{"metric_id": "order_count"}], filters=[filter_]))
        assert result.rows == ((sum(1 for r in ORDERS if predicate(r)),),), filter_


def test_a_string_value_that_looks_like_sql_is_data_not_syntax(gateway, contract, engine):
    hostile = "paid'; DROP TABLE sales_orders; --"
    _, result = _run(
        gateway,
        contract,
        _intent(
            metrics=[{"metric_id": "order_count"}],
            filters=[{"field_id": "orders.status", "operator": "equals", "values": [hostile]}],
        ),
    )
    assert result.rows == ((0,),)
    assert _scalar(engine, "SELECT COUNT(*) FROM sales_orders") == ORDER_COUNT


def test_time_range_bounds_inclusive_and_exclusive_end(gateway, contract):
    start, end = datetime(2024, 1, 2), datetime(2024, 1, 5)
    for inclusive in (True, False):
        intent = _intent(
            metrics=[{"metric_id": "order_count"}],
            time_range={"dimension_id": "created_at", "start": start, "end": end, "inclusive_end": inclusive},
        )
        _, result = _run(gateway, contract, intent)
        in_range = [
            r
            for r in ORDERS
            if start <= r["created_at"] and (r["created_at"] <= end if inclusive else r["created_at"] < end)
        ]
        assert result.rows == ((len(in_range),),)


@pytest.mark.parametrize("granularity", ["day", "week", "month", "quarter", "year"])
def test_every_time_granularity_buckets_like_python(gateway, contract, granularity):
    intent = _intent(
        metrics=[{"metric_id": "order_count"}],
        group_by=[{"dimension_id": "created_at", "time_granularity": granularity}],
        sort=[{"target_kind": "dimension", "target_id": "created_at", "direction": "asc"}],
    )
    _, result = _run(gateway, contract, intent)

    def bucket(moment: datetime) -> datetime:
        day = datetime(moment.year, moment.month, moment.day)
        return {
            "day": day,
            "week": day - timedelta(days=day.weekday()),  # PostgreSQL weeks start on Monday
            "month": day.replace(day=1),
            "quarter": day.replace(month=3 * ((day.month - 1) // 3) + 1, day=1),
            "year": day.replace(month=1, day=1),
        }[granularity]

    expected = {key: len(rows) for key, rows in _expected(ORDERS, key=lambda r: bucket(r["created_at"])).items()}
    assert dict(result.rows) == expected
    assert [row[0] for row in result.rows] == sorted(expected)
    assert all(isinstance(row[0], datetime) for row in result.rows)


def test_sort_direction_and_limit_are_applied_by_the_server(gateway, contract):
    intent = _intent(
        metrics=[{"metric_id": "order_count"}],
        group_by=[{"dimension_id": "customer"}],
        sort=[
            {"target_kind": "metric", "target_id": "order_count", "direction": "desc"},
            {"target_kind": "dimension", "target_id": "customer", "direction": "asc"},
        ],
        limit=5,
    )
    _, result = _run(gateway, contract, intent)
    counts = {key: len(rows) for key, rows in _expected(ORDERS, key=lambda r: r["customer_id"]).items()}
    expected = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    assert [(row[0], row[1]) for row in result.rows] == expected
    assert not result.truncated  # LIMIT is the query's own bound, not a truncation


def test_min_cohort_having_clause_hides_small_groups(gateway, contract):
    intent = _intent(metrics=[{"metric_id": "order_count"}], group_by=[{"dimension_id": "status"}])
    threshold = 101
    sizes = {key: len(rows) for key, rows in _expected(ORDERS).items()}
    _, result = _run(gateway, contract, intent, compiler=PostgreSQLCompiler(min_cohort=threshold))
    assert dict(result.rows) == {key: size for key, size in sizes.items() if size >= threshold}


def test_sort_places_null_groups_last_in_both_directions(gateway, contract):
    """The compiler states NULLS LAST, so the order no longer depends on each engine's default (PostgreSQL: first for DESC)."""
    base = {"metrics": [{"metric_id": "order_count"}], "group_by": [{"dimension_id": "status"}]}
    ascending = _run(
        gateway,
        contract,
        _intent(sort=[{"target_kind": "dimension", "target_id": "status", "direction": "asc"}], **base),
    )[1]
    descending = _run(
        gateway,
        contract,
        _intent(sort=[{"target_kind": "dimension", "target_id": "status", "direction": "desc"}], **base),
    )[1]
    assert ascending.rows[-1][0] is None
    assert descending.rows[-1][0] is None


def test_names_that_need_quoting_execute(gateway):
    plan = _plan(
        'SELECT d0."Ship ""Mode""" AS dimension_0, SUM(d0."Line Total") AS metric_0 FROM "Order Items" AS d0'
        ' WHERE d0."select" = :p0 AND d0."Ordered At" >= :p1 GROUP BY 1 ORDER BY metric_0 DESC NULLS LAST LIMIT 10',
        p0="a",
        p1=datetime(2024, 3, 1),
    )
    result = gateway.execute(plan, limits=ExecutionLimits())
    assert result.rows == (("air", Decimal("10.50")), ("sea", Decimal("4.25")))


def test_compiler_quoting_of_awkward_physical_names_runs_on_the_server(gateway):
    contract = SemanticContract.model_validate(
        {
            "id": "items",
            "tenant_id": "tenant-a",
            "domain": "sales",
            "version": "v1",
            "owners": [{"id": "team.data", "display_name": "Data", "owner_type": "team"}],
            "datasets": [
                {
                    "id": "items",
                    "display_name": "Items",
                    "source_asset_id": "warehouse.items",
                    "physical_name": "Order Items",
                    "description": "Line items",
                    "owner_ids": ["team.data"],
                }
            ],
            "fields": [
                _field("items.total", "items", "Line Total", "decimal"),
                _field("items.mode", "items", 'Ship "Mode"', "string"),
                _field("items.key", "items", "select", "string"),
            ],
            "dimensions": [
                {
                    "id": "mode",
                    "dataset_id": "items",
                    "field_id": "items.mode",
                    "dimension_type": "categorical",
                    "owner_ids": ["team.data"],
                }
            ],
            "metrics": [
                {
                    "id": "total",
                    "dataset_id": "items",
                    "aggregation": "sum",
                    "measure_field_id": "items.total",
                    "grain": {"kind": "item", "key_field_ids": ["items.key"]},
                    "certification": "certified",
                    "owner_ids": ["team.data"],
                }
            ],
        }
    )
    intent = AnalyticalIntent.model_validate(
        {
            "query_id": "q-2",
            "tenant_id": "tenant-a",
            "dataset_id": "items",
            "semantic_contract": {"contract_id": "items", "contract_version": "v1"},
            "metrics": [{"metric_id": "total"}],
            "group_by": [{"dimension_id": "mode"}],
            "sort": [{"target_kind": "metric", "target_id": "total", "direction": "desc"}],
            "limit": 10,
        }
    )
    _, result = _run(gateway, contract, intent)
    assert result.rows == (("air", Decimal("17.50")), ("sea", Decimal("4.25")))


def test_estimate_returns_the_planner_cost_and_scales_with_table_size(gateway):
    small = gateway.estimate(_plan("SELECT COUNT(*) AS n FROM sales_orders"))
    large = gateway.estimate(_plan(SLOW_SQL))
    assert 0 < small < large
    assert (
        GatewayCostEstimator({"postgres": gateway}).estimate(_plan("SELECT COUNT(*) AS n FROM sales_orders")) == small
    )


# ---- read-only guarantees ----


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM sales_orders",
        "UPDATE sales_orders SET status = 'x'",
        "INSERT INTO sales_orders (id) VALUES ('x')",
        "DROP TABLE sales_orders",
        "CREATE TABLE evil AS SELECT * FROM sales_orders",
        "TRUNCATE sales_orders",
        "ALTER TABLE sales_orders ADD COLUMN x int",
        "GRANT ALL ON sales_orders TO PUBLIC",
        "COPY sales_orders TO '/tmp/leak.csv'",
        "SELECT * INTO evil FROM sales_orders",
        "SELECT id FROM sales_orders FOR UPDATE",
        "WITH gone AS (DELETE FROM sales_orders RETURNING id) SELECT id FROM gone",
        "SELECT id FROM sales_orders; DROP TABLE sales_orders",
        "SELECT nextval('audit_seq') FROM sales_orders",
        "SELECT write_probe() FROM sales_orders",
        "SELECT pg_sleep(30) FROM sales_orders",
        "SELECT set_config('transaction_read_only', 'off', true) FROM sales_orders",
        "SELECT * FROM pg_catalog.pg_authid",
        "SELECT * FROM information_schema.tables",
        "SELECT * FROM pg_user",
        'SELECT status FROM "Sales_Orders"',
        "SELECT * FROM write_audit",
    ],
)
def test_unsafe_or_out_of_scope_sql_is_refused_before_a_connection_is_used(sql, engine, server):
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    with pytest.raises(QueryRejected):
        gateway.execute(_plan(sql), limits=ExecutionLimits())
    assert engine.pool.checkedout() == 0 and engine.pool.checkedin() == 0  # no connection was even opened


def test_quoted_name_differing_only_by_case_does_not_borrow_the_allowlisted_table(engine):
    """ "Sales_Orders" is a different table from sales_orders in PostgreSQL; a lower-cased allowlist compare let it through."""
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    with pytest.raises(QueryRejected):
        gateway.execute(_plan('SELECT status FROM "Sales_Orders"'), limits=ExecutionLimits())
    # unquoted references fold to lower case on the server, so they still match the lower-case entry
    assert gateway.execute(_plan("SELECT COUNT(*) AS n FROM SALES_ORDERS"), limits=ExecutionLimits()).rows == (
        (ORDER_COUNT,),
    )
    # and a mixed-case allowlist entry names exactly the quoted table
    exact = PostgresGateway(engine, allowed_tables=["Order Items"])
    assert exact.execute(_plan('SELECT COUNT(*) AS n FROM "Order Items"'), limits=ExecutionLimits()).rows == ((3,),)
    with pytest.raises(QueryRejected):
        exact.execute(_plan('SELECT COUNT(*) AS n FROM "order items"'), limits=ExecutionLimits())


def test_server_refuses_writes_even_if_validation_were_bypassed_and_the_role_could_write(owner_engine, monkeypatch):
    """Defense in depth: connect as the table owner (who may write) with the AST guard disabled."""
    gateway = PostgresGateway(owner_engine, allowed_tables=["sales_orders"])
    monkeypatch.setattr(gateway, "_check", lambda plan: None)
    before = (
        _scalar(owner_engine, "SELECT COUNT(*) FROM write_audit"),
        _scalar(owner_engine, "SELECT last_value FROM audit_seq"),
    )
    for sql in (
        "SELECT write_probe()",  # a function that INSERTs
        "SELECT nextval('audit_seq')",  # sequences are writes too
        "SELECT set_config('transaction_read_only', 'off', true)",  # cannot flip the transaction back to read-write
    ):
        with pytest.raises(ExecutionError) as caught:
            gateway.execute(_plan(sql), limits=ExecutionLimits())
        assert str(caught.value).startswith("query failed: ")
    after = (
        _scalar(owner_engine, "SELECT COUNT(*) FROM write_audit"),
        _scalar(owner_engine, "SELECT last_value FROM audit_seq"),
    )
    assert before == after == (0, 1)


def test_least_privilege_role_cannot_read_other_tables_even_if_validation_were_bypassed(engine, monkeypatch):
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    monkeypatch.setattr(gateway, "_check", lambda plan: None)
    with pytest.raises(ExecutionError) as caught:
        gateway.execute(_plan("SELECT COUNT(*) AS n FROM write_audit"), limits=ExecutionLimits())
    assert "InsufficientPrivilege" in str(caught.value)


def test_each_execution_runs_in_a_read_only_transaction_with_utc_and_the_requested_timeout(
    engine, gateway, monkeypatch
):
    seen = {}
    original = PostgresGateway._explain_cost

    def spy(connection, plan):
        for name in ("transaction_read_only", "statement_timeout", "lock_timeout", "TimeZone"):
            seen[name] = connection.exec_driver_sql(f"SHOW {name}").scalar()
        return original(connection, plan)

    monkeypatch.setattr(PostgresGateway, "_explain_cost", staticmethod(spy))
    gateway.execute(_plan("SELECT COUNT(*) AS n FROM sales_orders"), limits=ExecutionLimits(timeout_seconds=7))
    assert seen == {"transaction_read_only": "on", "statement_timeout": "7s", "lock_timeout": "7s", "TimeZone": "UTC"}


def test_session_settings_do_not_leak_to_the_next_user_of_the_pooled_connection(server):
    engine = create_engine(server["ro_url"], pool_size=1, max_overflow=0)
    try:
        PostgresGateway(engine, allowed_tables=["sales_orders"]).execute(
            _plan("SELECT COUNT(*) AS n FROM sales_orders"), limits=ExecutionLimits(timeout_seconds=3)
        )
        with engine.connect() as connection:  # the very same pooled connection
            assert connection.exec_driver_sql("SHOW transaction_read_only").scalar() == "off"
            assert connection.exec_driver_sql("SHOW statement_timeout").scalar() == "0"
            assert connection.exec_driver_sql("SHOW lock_timeout").scalar() == "0"
            connection.rollback()
    finally:
        engine.dispose()


# ---- limits, truncation, timeout, cancellation ----


def test_row_cap_truncates_and_exact_fit_does_not(gateway):
    sql = "SELECT id FROM sales_events ORDER BY id"
    capped = gateway.execute(_plan(sql), limits=ExecutionLimits(max_rows=2_500))
    assert capped.row_count == 2_500 and capped.truncated and capped.truncation_reason == "max_rows"
    assert [row[0] for row in capped.rows[:3]] == [1, 2, 3]  # the first rows, in order
    exact = gateway.execute(_plan(sql), limits=ExecutionLimits(max_rows=EVENT_COUNT))
    assert exact.row_count == EVENT_COUNT and not exact.truncated and exact.truncation_reason is None


def test_byte_cap_truncates(gateway):
    result = gateway.execute(_plan("SELECT id FROM sales_events"), limits=ExecutionLimits(max_bytes=1_000))
    assert result.truncated and result.truncation_reason == "max_bytes"
    assert 0 < result.row_count < 1_000 and result.byte_count <= 1_000


def test_truncated_stream_releases_the_server_cursor_and_connection(server):
    engine = create_engine(server["ro_url"], pool_size=1, max_overflow=0, pool_timeout=3)
    try:
        gateway = PostgresGateway(engine, allowed_tables=["sales_events"])
        for _ in range(3):  # a leaked cursor or transaction would block or pile up here
            gateway.execute(_plan("SELECT id FROM sales_events"), limits=ExecutionLimits(max_rows=10))
        assert engine.pool.checkedout() == 0
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM pg_cursors").scalar() == 0
            connection.rollback()
    finally:
        engine.dispose()


def test_cost_ceiling_blocks_the_query_before_it_runs(gateway, engine):
    started = time.perf_counter()
    with pytest.raises(CostLimitExceeded):
        gateway.execute(_plan(SLOW_SQL), limits=ExecutionLimits(max_cost_units=1_000, timeout_seconds=30))
    assert time.perf_counter() - started < 5  # refused from the EXPLAIN, not by running into the timeout
    assert engine.pool.checkedout() == 0
    result = gateway.execute(
        _plan("SELECT COUNT(*) AS n FROM sales_orders"), limits=ExecutionLimits(max_cost_units=1_000)
    )
    assert 0 < result.estimated_cost_units <= 1_000


def test_statement_timeout_stops_a_runaway_query_on_the_server(gateway, engine):
    started = time.perf_counter()
    with pytest.raises(ExecutionTimeout):
        gateway.execute(_plan(SLOW_SQL), limits=ExecutionLimits(timeout_seconds=1, max_cost_units=1e15))
    assert 0.9 < time.perf_counter() - started < 4
    assert engine.pool.checkedout() == 0


def test_the_server_is_idle_after_a_timeout(server, owner_engine):
    engine = create_engine(server["ro_url"], pool_size=1, max_overflow=0)
    try:
        with pytest.raises(ExecutionTimeout):
            PostgresGateway(engine, allowed_tables=["sales_events"]).execute(
                _plan(SLOW_SQL), limits=ExecutionLimits(timeout_seconds=1, max_cost_units=1e15)
            )
        busy = _scalar(
            owner_engine,
            f"SELECT COUNT(*) FROM pg_stat_activity WHERE datname = '{server['database']}' AND usename <> current_user"
            " AND state <> 'idle'",
        )
        assert busy == 0
    finally:
        engine.dispose()


def test_cancel_during_the_run_stops_the_query_and_is_not_reported_as_a_timeout(gateway, engine):
    token = CancellationToken()
    threading.Timer(0.7, token.cancel).start()
    started = time.perf_counter()
    with pytest.raises(ExecutionCancelled):
        gateway.execute(
            _plan(SLOW_SQL), limits=ExecutionLimits(timeout_seconds=20, max_cost_units=1e15), cancellation=token
        )
    assert time.perf_counter() - started < 6  # nowhere near the 20 second timeout
    assert engine.pool.checkedout() == 0


def test_a_token_cancelled_before_the_call_never_starts_the_query(gateway, engine):
    token = CancellationToken()
    token.cancel()
    started = time.perf_counter()
    with pytest.raises(ExecutionCancelled):
        gateway.execute(
            _plan(SLOW_SQL), limits=ExecutionLimits(timeout_seconds=20, max_cost_units=1e15), cancellation=token
        )
    assert (
        time.perf_counter() - started < 1
    )  # a cancel sent to an idle connection is dropped, so the run must not begin
    assert engine.pool.checkedout() == 0


def test_the_gateway_is_usable_again_after_every_failure_mode(gateway, engine):
    for _ in range(2):
        with pytest.raises(ExecutionTimeout):
            gateway.execute(_plan(SLOW_SQL), limits=ExecutionLimits(timeout_seconds=1, max_cost_units=1e15))
        with pytest.raises(ExecutionError):
            gateway.execute(_plan("SELECT 1 / 0 AS n FROM sales_orders"), limits=ExecutionLimits())
    result = gateway.execute(_plan("SELECT COUNT(*) AS n FROM sales_orders"), limits=ExecutionLimits())
    assert result.rows == ((ORDER_COUNT,),)
    assert engine.pool.checkedout() == 0


def test_concurrent_executions_are_isolated_from_each_other(gateway, contract):
    results, errors = [], []

    def worker(status):
        try:
            intent = _intent(
                metrics=[{"metric_id": "order_count"}],
                filters=[{"field_id": "orders.status", "operator": "equals", "values": [status]}],
            )
            results.append(
                (
                    status,
                    gateway.execute(
                        PostgreSQLCompilerAdapter().compile(intent, contract), limits=ExecutionLimits()
                    ).rows[0][0],
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    statuses = ["paid", "refunded", "cancelled"]
    threads = [threading.Thread(target=worker, args=(status,)) for status in statuses]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(20)
    assert not errors
    assert dict(results) == {status: sum(1 for r in ORDERS if r["status"] == status) for status in statuses}


# ---- error mapping ----


def test_server_errors_are_mapped_to_a_type_name_only(gateway):
    secrets_in_play = "ultra_secret_marker"
    for sql, expected in (
        (f"SELECT {secrets_in_play} FROM sales_orders", "UndefinedColumn"),
        ("SELECT 1 / 0 AS n FROM sales_orders", "DivisionByZero"),
        ("SELECT CAST(status AS integer) AS n FROM sales_orders WHERE status = :p0", "InvalidTextRepresentation"),
    ):
        with pytest.raises(ExecutionError) as caught:
            gateway.execute(_plan(sql, p0="paid"), limits=ExecutionLimits())
        assert str(caught.value) == f"query failed: {expected}"
        assert secrets_in_play not in str(caught.value) and "sales_orders" not in str(caught.value)


def test_an_unbound_marker_is_refused_without_a_connection_or_the_sql_in_the_message(engine):
    gateway = PostgresGateway(engine, allowed_tables=["sales_orders"])
    for call in (gateway.execute, gateway.estimate):
        with pytest.raises(QueryRejected) as caught:
            call(
                _plan("SELECT COUNT(*) AS n FROM sales_orders WHERE status = :p0"),
                **({"limits": ExecutionLimits()} if call == gateway.execute else {}),
            )
        assert "sales_orders" not in str(caught.value)
    assert engine.pool.checkedout() == 0 and engine.pool.checkedin() == 0


def test_connection_failures_do_not_leak_credentials_or_hosts(server):
    gateway_args = {"allowed_tables": ["sales_orders"]}
    wrong_password = create_engine(server["ro_url"].set(password="not-the-password"))
    try:
        wrong_password.connect().close()
    except Exception:
        pass
    else:
        wrong_password.dispose()
        pytest.skip("the server accepted a wrong password (trust authentication); start it with scram-sha-256 or md5")
    unreachable = create_engine(
        URL.create(
            "postgresql+psycopg2",
            username="u",
            password="p4ss-w0rd",
            host="db.internal.example",
            port=9,
            database="d",
            query={"connect_timeout": "1"},
        )
    )
    try:
        for engine in (wrong_password, unreachable):
            gateway = PostgresGateway(engine, **gateway_args)
            for call in (
                lambda g: g.execute(_plan("SELECT COUNT(*) AS n FROM sales_orders"), limits=ExecutionLimits()),
                lambda g: g.estimate(_plan("SELECT COUNT(*) AS n FROM sales_orders")),
            ):
                with pytest.raises(ExecutionError) as caught:
                    call(gateway)
                message = f"{caught.value} {caught.value!r}"
                for forbidden in (
                    "not-the-password",
                    "p4ss-w0rd",
                    "db.internal.example",
                    "127.0.0.1",
                    "55432",
                    server["database"],
                    "sales_orders",
                ):
                    assert forbidden not in message
    finally:
        wrong_password.dispose()
        unreachable.dispose()


def test_pool_exhaustion_is_an_execution_error_not_a_raw_driver_error(server):
    engine = create_engine(server["ro_url"], pool_size=1, max_overflow=0, pool_timeout=1)
    held = engine.connect()
    try:
        with pytest.raises(ExecutionError) as caught:
            PostgresGateway(engine, allowed_tables=["sales_orders"]).execute(
                _plan("SELECT COUNT(*) AS n FROM sales_orders"), limits=ExecutionLimits()
            )
        assert type(caught.value) is ExecutionError and str(caught.value).startswith("query failed: ")
    finally:
        held.close()
        engine.dispose()


def test_a_backend_killed_mid_query_is_a_clean_execution_error(server, owner_engine):
    engine = create_engine(server["ro_url"], pool_size=1, max_overflow=0)
    gateway = PostgresGateway(engine, allowed_tables=["sales_events"])
    try:

        def terminate():
            time.sleep(0.8)
            _scalar(
                owner_engine,
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '{server['database']}' AND usename <> current_user"
                " AND state = 'active' AND pid <> pg_backend_pid()",
            )

        killer = threading.Thread(target=terminate)
        killer.start()
        with pytest.raises(ExecutionError) as caught:
            gateway.execute(_plan(SLOW_SQL), limits=ExecutionLimits(timeout_seconds=20, max_cost_units=1e15))
        killer.join()
        assert str(caught.value).startswith("query failed: ") and "sales_events" not in str(caught.value)
        # the pool recovers on the next call: the dead connection is discarded, not reused
        assert gateway.execute(_plan("SELECT COUNT(*) AS n FROM sales_events"), limits=ExecutionLimits()).rows == (
            (EVENT_COUNT,),
        )
    finally:
        engine.dispose()
