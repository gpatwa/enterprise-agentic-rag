"""W3/W7: Snowflake and Databricks metadata providers against a recording fake query runner."""

from __future__ import annotations

import pytest

from app.metadata import DatabricksMetadataProvider, SnowflakeMetadataProvider

ROWS = [("ID", "NUMBER", "NO"), ("STATUS", "TEXT", "YES"), ("CREATED_AT", "TIMESTAMP_NTZ", "YES")]


class Runner:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def __call__(self, sql, parameters):
        self.calls.append((sql, dict(parameters)))
        return self.rows


def _providers(runner):
    return {
        "snowflake": SnowflakeMetadataProvider(runner, database="ANALYTICS", schema="PUBLIC"),
        "databricks": DatabricksMetadataProvider(runner, catalog="main", schema="sales"),
    }


@pytest.mark.parametrize("name", ["snowflake", "databricks"])
def test_normalizes_columns_and_nullability(name):
    runner = Runner(ROWS)

    snapshot = _providers(runner)[name].get_snapshot("ORDERS")

    asset = snapshot.assets[0]
    assert snapshot.provider == name and asset.provider == name
    assert asset.physical_name == "ORDERS" and asset.id.endswith(".ORDERS")
    assert [(c.name, c.data_type, c.nullable) for c in asset.columns] == [
        ("ID", "NUMBER", False),
        ("STATUS", "TEXT", True),
        ("CREATED_AT", "TIMESTAMP_NTZ", True),
    ]


def test_snowflake_query_is_a_single_select_with_a_quoted_database_and_bound_names():
    runner = Runner(ROWS)

    _providers(runner)["snowflake"].get_snapshot("ORDERS")

    sql, parameters = runner.calls[0]
    assert sql.startswith("SELECT ") and ";" not in sql
    assert 'FROM "ANALYTICS".information_schema.columns' in sql
    assert parameters == {"table_schema": "PUBLIC", "table_name": "ORDERS"}


def test_databricks_query_uses_backticks_for_the_catalog():
    runner = Runner(ROWS)

    _providers(runner)["databricks"].get_snapshot("orders")

    sql, parameters = runner.calls[0]
    assert "FROM `main`.information_schema.columns" in sql
    assert parameters == {"table_schema": "sales", "table_name": "orders"}


@pytest.mark.parametrize("name", ["snowflake", "databricks"])
def test_an_injection_shaped_table_name_travels_as_a_bind_value_only(name):
    runner = Runner(ROWS)
    hostile = "x' OR '1'='1'; DROP TABLE t; --"

    _providers(runner)[name].get_snapshot(hostile)

    sql, parameters = runner.calls[0]
    assert hostile not in sql and parameters["table_name"] == hostile


@pytest.mark.parametrize(
    "catalog",
    ['a"; DROP', "a:p1", "a%s", "", " a", "a\nb"],
)
def test_a_hostile_database_or_catalog_name_is_refused_at_construction(catalog):
    runner = Runner(ROWS)

    with pytest.raises(ValueError):
        SnowflakeMetadataProvider(runner, database=catalog, schema="PUBLIC")
    with pytest.raises(ValueError):
        DatabricksMetadataProvider(runner, catalog=catalog, schema="sales")
    assert runner.calls == []


@pytest.mark.parametrize("name", ["snowflake", "databricks"])
def test_a_missing_or_invisible_table_raises_instead_of_returning_an_empty_asset(name):
    with pytest.raises(LookupError):
        _providers(Runner([]))[name].get_snapshot("NOPE")


@pytest.mark.parametrize("name", ["snowflake", "databricks"])
def test_blank_asset_and_schema_are_refused(name):
    provider = _providers(Runner(ROWS))[name]

    with pytest.raises(ValueError):
        provider.get_snapshot("  ")
    with pytest.raises(ValueError):
        SnowflakeMetadataProvider(Runner(ROWS), database="D", schema=" ")
