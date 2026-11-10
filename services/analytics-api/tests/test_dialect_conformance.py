"""W1: every registered SQL dialect compiles the same certified intents to read-only, parseable SQL.

No engine is contacted. Golden SQL pins each dialect's quoting; a dialect added later must be added to
DIALECTS and pass the same checks.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
import sqlglot

from app.compiler import (
    CompilationError,
    CompilerRegistry,
    DatabricksCompilerAdapter,
    DuckDBCompilerAdapter,
    PostgreSQLCompilerAdapter,
    SnowflakeCompilerAdapter,
)
from app.execution.validation import validate_read_only_sql
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract

ROOT = Path(__file__).parent.parent
ADAPTERS = {
    "postgres": PostgreSQLCompilerAdapter,
    "duckdb": DuckDBCompilerAdapter,
    "snowflake": SnowflakeCompilerAdapter,
    "databricks": DatabricksCompilerAdapter,
}
DIALECTS = tuple(ADAPTERS)
GOLDEN_INTENT = json.loads((ROOT / "tests/fixtures/semantic/sales-monthly-intent.json").read_text())


def _contract(*, dataset_name: str = "sales_orders", status_name: str = "status") -> SemanticContract:
    document = SemanticRegistry(ROOT / "semantic_registry").get_certified("sales-core", "v1")
    payload = copy.deepcopy(document.contract.model_dump(mode="json"))
    payload["datasets"][0]["physical_name"] = dataset_name
    for field in payload["fields"]:
        if field["id"] == "orders.status":
            field["physical_name"] = status_name
    return SemanticContract.model_validate(payload)


def _intent(**overrides) -> AnalyticalIntent:
    return AnalyticalIntent.model_validate({**copy.deepcopy(GOLDEN_INTENT), **overrides})


INTENTS = {
    "golden-monthly": _intent(),
    "by-status": _intent(group_by=[{"dimension_id": "status"}], time_range=None, filters=[], sort=[], limit=10),
    "in-filter": _intent(
        group_by=[{"dimension_id": "created_at", "time_granularity": "week"}],
        filters=[{"field_id": "orders.status", "operator": "in", "values": ["paid", "shipped"]}],
        time_range=None,
    ),
    "not-in-filter": _intent(
        group_by=[{"dimension_id": "status"}],
        filters=[{"field_id": "orders.status", "operator": "not_in", "values": ["cancelled"]}],
        time_range=None,
        sort=[],
    ),
}

GOLDEN_SQL = {
    "postgres": (
        'SELECT DATE_TRUNC(\'month\', d0."created_at") AS dimension_0, SUM(d0."amount") AS metric_0\n'
        'FROM "sales_orders" AS d0\n'
        'WHERE d0."status" = :p0 AND d0."created_at" >= :p1 AND d0."created_at" <= :p2\n'
        "GROUP BY 1\nORDER BY metric_0 DESC NULLS LAST\nLIMIT 25"
    ),
    "databricks": (
        "SELECT DATE_TRUNC('month', d0.`created_at`) AS dimension_0, SUM(d0.`amount`) AS metric_0\n"
        "FROM `sales_orders` AS d0\n"
        "WHERE d0.`status` = :p0 AND d0.`created_at` >= :p1 AND d0.`created_at` <= :p2\n"
        "GROUP BY 1\nORDER BY metric_0 DESC NULLS LAST\nLIMIT 25"
    ),
}
GOLDEN_SQL["duckdb"] = GOLDEN_SQL["snowflake"] = GOLDEN_SQL["postgres"]


@pytest.mark.parametrize("intent_name", INTENTS)
@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_dialect_compiles_to_parseable_read_only_sql(dialect, intent_name):
    compiled = ADAPTERS[dialect]().compile(INTENTS[intent_name], _contract())

    assert compiled.dialect == dialect
    assert compiled.sql.count(";") == 0
    validate_read_only_sql(compiled.sql, dialect=dialect, allowed_tables={"sales_orders"})
    sqlglot.parse_one(compiled.sql, read=dialect)


@pytest.mark.parametrize("intent_name", INTENTS)
def test_dialects_agree_on_bind_parameters(intent_name):
    parameters = {
        dialect: ADAPTERS[dialect]().compile(INTENTS[intent_name], _contract()).parameters for dialect in DIALECTS
    }

    assert len({json.dumps(value, sort_keys=True, default=str) for value in parameters.values()}) == 1


@pytest.mark.parametrize("dialect", DIALECTS)
def test_golden_sql_per_dialect(dialect):
    assert ADAPTERS[dialect]().compile(INTENTS["golden-monthly"], _contract()).sql == GOLDEN_SQL[dialect]


@pytest.mark.parametrize("dialect", DIALECTS)
def test_min_cohort_having_clause_is_emitted_for_every_dialect(dialect):
    adapter = ADAPTERS[dialect](min_cohort=5)

    assert "HAVING COUNT(*) >= 5" in adapter.compile(INTENTS["by-status"], _contract()).sql


def test_registry_holds_all_dialects_and_fails_closed_on_an_unknown_one():
    registry = CompilerRegistry([adapter() for adapter in ADAPTERS.values()])

    assert {registry.get(name).dialect for name in DIALECTS} == set(DIALECTS)
    with pytest.raises(LookupError):
        registry.get("oracle")


BAD_COLUMN_NAMES = ['x"; DROP TABLE t; --', "a:p1", "a%s", " lead", "trail ", "a\nb", "a\\b"]


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
@pytest.mark.parametrize("bad_name", BAD_COLUMN_NAMES + ["a.b.c.d", "a..b"])
def test_warehouse_dialects_refuse_unquotable_table_names(dialect, bad_name):
    with pytest.raises(CompilationError):
        ADAPTERS[dialect]().compile(INTENTS["golden-monthly"], _contract(dataset_name=bad_name))


@pytest.mark.parametrize("dialect", ["snowflake", "databricks"])
@pytest.mark.parametrize("bad_name", BAD_COLUMN_NAMES)
def test_warehouse_dialects_refuse_unquotable_column_names(dialect, bad_name):
    # Statement-ending and bind-marker characters are refused. (An empty name is already rejected
    # by the contract model, and a dot inside one column name is legal once quoted.)
    with pytest.raises(CompilationError):
        ADAPTERS[dialect]().compile(INTENTS["golden-monthly"], _contract(status_name=bad_name))


def test_snowflake_quotes_embedded_double_quotes_and_keeps_case():
    sql = (
        SnowflakeCompilerAdapter()
        .compile(
            INTENTS["golden-monthly"], _contract(dataset_name="ANALYTICS.PUBLIC.SALES_ORDERS", status_name='St"atus')
        )
        .sql
    )

    assert 'FROM "ANALYTICS"."PUBLIC"."SALES_ORDERS" AS d0' in sql
    assert 'd0."St""atus" = :p0' in sql


def test_databricks_quotes_embedded_backticks_and_three_part_tables():
    sql = (
        DatabricksCompilerAdapter()
        .compile(INTENTS["golden-monthly"], _contract(dataset_name="main.sales.orders", status_name="st`atus"))
        .sql
    )

    assert "FROM `main`.`sales`.`orders` AS d0" in sql
    assert "d0.`st``atus` = :p0" in sql
    validate_read_only_sql(sql, dialect="databricks", allowed_tables={"main.sales.orders"})


def test_postgres_output_is_unchanged_for_names_the_warehouse_dialects_refuse():
    # Historical behavior is preserved for the two existing engines; only the new dialects add the checks.
    sql = PostgreSQLCompilerAdapter().compile(INTENTS["golden-monthly"], _contract(status_name="a:b")).sql

    assert 'd0."a:b" = :p0' in sql
