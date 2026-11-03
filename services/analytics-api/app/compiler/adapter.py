"""Compiler adapter boundary for future SQL dialect implementations."""
from __future__ import annotations

from typing import Any, Protocol

from app.compiler.dialects import DATABRICKS, DUCKDB, SNOWFLAKE, SQLDialect
from app.compiler.postgres import CompiledQuery, PostgreSQLCompiler
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract


class CompilerAdapter(Protocol):
    dialect: str

    def compile(
        self,
        intent: AnalyticalIntent,
        contract: SemanticContract,
        policy_values: dict[str, Any] | None = None,
    ) -> CompiledQuery:
        ...


class PostgreSQLCompilerAdapter(PostgreSQLCompiler):
    """Named adapter used by the production selection point."""

    dialect = "postgres"


class DuckDBCompilerAdapter(PostgreSQLCompiler):
    """DuckDB shares the PostgreSQL subset this compiler emits (DATE_TRUNC, ANSI aggregates).

    The separate dialect tag lets an execution gateway refuse a plan compiled for
    another engine; bind parameters are converted by the gateway, not here.
    """

    dialect = "duckdb"
    sql_dialect: SQLDialect = DUCKDB


class SnowflakeCompilerAdapter(PostgreSQLCompiler):
    """Snowflake: quoted identifiers keep their case, so a contract must state the physical case.

    Tables may be `database.schema.table`. Bind parameters stay `:pN` here; the gateway converts them.
    """

    dialect = "snowflake"
    sql_dialect: SQLDialect = SNOWFLAKE


class DatabricksCompilerAdapter(PostgreSQLCompiler):
    """Databricks SQL: backtick-quoted identifiers; tables may be `catalog.schema.table` (Unity Catalog)."""

    dialect = "databricks"
    sql_dialect: SQLDialect = DATABRICKS


class CompilerRegistry:
    """Register dialect adapters without coupling the planner to SQL details."""

    def __init__(self, adapters: list[CompilerAdapter] | None = None):
        self._adapters: dict[str, CompilerAdapter] = {}
        for adapter in adapters or []:
            self.register(adapter)

    def register(self, adapter: CompilerAdapter) -> None:
        if adapter.dialect in self._adapters:
            raise ValueError(f"compiler dialect already registered: {adapter.dialect}")
        self._adapters[adapter.dialect] = adapter

    def get(self, dialect: str) -> CompilerAdapter:
        try:
            return self._adapters[dialect]
        except KeyError as exc:
            raise LookupError(f"compiler dialect is not registered: {dialect}") from exc
