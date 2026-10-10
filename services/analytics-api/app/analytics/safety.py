"""PostgreSQL AST validation and execution cost guards for analytics SQL.

This validator is a query-shape guard, not an authorization boundary. Later
semantic compilation and policy milestones will determine what a caller may
query; this module ensures generated SQL is a single, read-only query against
the locally configured physical-table allowlist.
"""
from __future__ import annotations

import logging
from typing import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from app.analytics.schema_context import OLIST_SCHEMA, get_all_table_names

logger = logging.getLogger(__name__)

_READ_ONLY_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
_MUTATING_EXPRESSIONS = tuple(
    expression
    for expression in (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Create,
        exp.Drop,
        exp.Alter,
        exp.TruncateTable,
        exp.Command,
        exp.Transaction,
        exp.Commit,
        exp.Rollback,
        exp.Grant,
        exp.Revoke,
    )
    if expression is not None
)
_ALLOWED_FUNCTIONS = {
    "abs", "avg", "cast", "coalesce", "concat", "count", "current_date",
    "current_timestamp", "dense_rank", "extract", "greatest", "lag", "lead",
    "least", "length", "lower", "max", "min", "nullif", "rank", "round",
    "row_number", "substring", "sum", "timestamp_trunc", "trim", "upper",
}


def validate_sql(sql: str) -> tuple[bool, str]:
    """Accept one PostgreSQL read-only query or return a stable failure message."""
    try:
        statements = sqlglot.parse(sql, read="postgres")
    except ParseError:
        return False, "[SQL_PARSE_ERROR] Query could not be parsed."

    if len(statements) != 1 or statements[0] is None:
        return False, "[SQL_MULTIPLE_STATEMENTS] Multiple SQL statements are not allowed."
    tree = statements[0]
    if not isinstance(tree, _READ_ONLY_ROOTS):
        return False, "[SQL_NOT_READ_ONLY] Only SELECT queries are allowed."
    if any(isinstance(node, _MUTATING_EXPRESSIONS) for node in tree.walk()):
        return False, "[SQL_NOT_READ_ONLY] Only SELECT queries are allowed."

    unsafe_function = _find_unsafe_function(tree)
    if unsafe_function:
        return False, f"[SQL_DISALLOWED_FUNCTION] Disallowed SQL function: {unsafe_function}"
    if any(isinstance(table.this, exp.Func) for table in tree.find_all(exp.Table)):
        return False, "[SQL_TABLE_FUNCTION] Table-valued functions are not allowed."

    cte_aliases = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    _, aliases, unknown_tables = _resolve_physical_tables(tree, cte_aliases)
    if unknown_tables:
        return False, f"[SQL_UNKNOWN_TABLE] Unknown tables referenced: {', '.join(sorted(unknown_tables))}"

    unknown_columns = _find_unknown_columns(tree, aliases)
    if unknown_columns:
        return False, f"[SQL_UNKNOWN_COLUMN] Unknown columns referenced: {', '.join(sorted(unknown_columns))}"

    return True, ""


def _resolve_physical_tables(
    tree: exp.Expression, cte_aliases: set[str]
) -> tuple[set[str], dict[str, str], set[str]]:
    valid_tables = {name.lower() for name in get_all_table_names()}
    physical_tables: set[str] = set()
    aliases: dict[str, str] = {}
    unknown_tables: set[str] = set()
    for table in tree.find_all(exp.Table):
        table_name = table.name.lower()
        schema_name = table.db.lower() if table.db else ""
        if table_name in cte_aliases and not schema_name:
            continue
        if schema_name or table_name not in valid_tables:
            unknown_tables.add(".".join(part for part in (schema_name, table_name) if part))
            continue
        physical_tables.add(table_name)
        aliases[table.alias_or_name.lower()] = table_name
        aliases[table_name] = table_name
    return physical_tables, aliases, unknown_tables


def _find_unknown_columns(tree: exp.Expression, aliases: dict[str, str]) -> set[str]:
    unknown: set[str] = set()
    for column in tree.find_all(exp.Column):
        prefix = column.table.lower() if column.table else ""
        table_name = aliases.get(prefix)
        if not table_name:
            continue
        columns = {name.lower() for name in OLIST_SCHEMA[table_name]["columns"]}
        if column.name.lower() not in columns:
            unknown.add(f"{table_name}.{column.name}")
    return unknown


def _find_unsafe_function(tree: exp.Expression) -> str | None:
    for function in tree.find_all(exp.Func):
        function_name = (
            function.name if isinstance(function, exp.Anonymous) else function.sql_name()
        ).lower()
        if function_name not in _ALLOWED_FUNCTIONS:
            return function_name
    return None


def _physical_tables(sql: str) -> Iterable[str]:
    """Return physical tables for cost checks after the AST validator has run."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except ParseError:
        return ()
    cte_aliases = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
    tables, _, _ = _resolve_physical_tables(tree, cte_aliases)
    return tables


def check_cost_guard(sql: str) -> tuple[bool, str]:
    """Reject unbounded scans of large configured physical tables."""
    try:
        tree = sqlglot.parse_one(sql, read="postgres")
    except ParseError:
        return False, "Unable to inspect query cost."

    if tree.find(exp.Where) or tree.find(exp.Limit) or tree.find(exp.Group):
        return True, ""
    for table_name in _physical_tables(sql):
        row_count = OLIST_SCHEMA[table_name].get("row_count_approx", 0)
        if row_count > 500_000:
            return False, (
                f"Table '{table_name}' has ~{row_count:,} rows. "
                "Add a WHERE clause, LIMIT, or GROUP BY to avoid full table scans."
            )
    return True, ""


def sanitize_result(rows: list[dict], max_rows: int) -> tuple[list[dict], bool]:
    """Cap returned rows while reporting whether any were omitted."""
    if len(rows) <= max_rows:
        return rows, False
    return rows[:max_rows], True
