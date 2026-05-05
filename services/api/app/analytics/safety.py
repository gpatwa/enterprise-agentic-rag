# services/api/app/analytics/safety.py
"""
SQL safety validation for the Data Analytics Agent.

Enforces:
- SELECT-only queries (no DDL/DML)
- Disallowed keyword rejection (DROP, pg_sleep, COPY, etc.)
- Table name allowlisting
- Cost guard for large tables without WHERE/LIMIT
- Result row cap
"""
import re
import logging
from typing import Tuple, List

from app.analytics.schema_context import get_all_table_names, OLIST_SCHEMA

logger = logging.getLogger(__name__)

# Keywords that should NEVER appear in generated SQL
_DISALLOWED_KEYWORDS = {
    "insert", "update", "delete", "drop", "alter", "create", "truncate",
    "grant", "revoke", "copy", "execute", "pg_sleep", "pg_read_file",
    "pg_write_file", "lo_import", "lo_export", "dblink",
}

# Regex to extract table names from FROM/JOIN clauses
_TABLE_REF_PATTERN = re.compile(
    r'\b(?:FROM|JOIN)\s+([a-zA-Z_][a-zA-Z0-9_]*)',
    re.IGNORECASE,
)


def validate_sql(sql: str) -> Tuple[bool, str]:
    """
    Validate that SQL is safe to execute.

    Returns:
        (is_safe, error_message) — error_message is empty if safe.
    """
    sql_stripped = sql.strip().rstrip(";")
    sql_lower = sql_stripped.lower()

    # Must start with SELECT or WITH (CTE)
    if not sql_lower.startswith(("select", "with")):
        return False, "Only SELECT queries are allowed."

    # Check for disallowed keywords
    # Tokenize to avoid matching substrings (e.g. "updated_at" contains "update")
    tokens = set(re.findall(r'\b[a-z_]+\b', sql_lower))
    blocked = tokens & _DISALLOWED_KEYWORDS
    if blocked:
        return False, f"Disallowed SQL keywords: {', '.join(sorted(blocked))}"

    # Validate table names against allowlist
    valid_tables = set(get_all_table_names())
    referenced_tables = set(_TABLE_REF_PATTERN.findall(sql_stripped))
    # Normalize to lowercase
    referenced_lower = {t.lower() for t in referenced_tables}
    # Extract CTE aliases (WITH alias AS ...) to exclude from unknown check
    cte_aliases = {m.lower() for m in re.findall(r'\bWITH\s+(\w+)\s+AS\b', sql_stripped, re.IGNORECASE)}
    cte_aliases |= {m.lower() for m in re.findall(r',\s*(\w+)\s+AS\s*\(', sql_stripped, re.IGNORECASE)}
    unknown = referenced_lower - valid_tables - cte_aliases - {"lateral", "unnest"}  # exclude SQL keywords & CTEs
    if unknown:
        return False, f"Unknown tables referenced: {', '.join(sorted(unknown))}"

    # Check for multiple statements (;)
    if ";" in sql_stripped:
        return False, "Multiple SQL statements are not allowed."

    # Per-table column allowlist check — catches LLM column hallucinations.
    unknown_cols = _find_unknown_columns(sql_stripped, referenced_lower - cte_aliases)
    if unknown_cols:
        return False, f"Unknown columns referenced: {', '.join(sorted(unknown_cols))}"

    return True, ""


_QUALIFIED_COL_PATTERN = re.compile(
    r'\b([a-zA-Z_][a-zA-Z0-9_]*)\.([a-zA-Z_][a-zA-Z0-9_]*)\b'
)


def _find_unknown_columns(sql: str, tables: set[str]) -> set[str]:
    """
    Verify any `table.column` reference in the SQL exists in the schema.

    Conservative: only flags columns where the table prefix is a real
    schema table (we don't try to resolve unprefixed columns since aliases
    make that ambiguous). Aliases (`o.column`) are skipped because we
    don't track FROM/JOIN aliases here — those slip past safely.
    """
    if not tables:
        return set()
    unknown: set[str] = set()
    for prefix, col in _QUALIFIED_COL_PATTERN.findall(sql):
        prefix_lower = prefix.lower()
        if prefix_lower not in tables:
            continue  # alias or unrelated qualifier — skip
        cols = OLIST_SCHEMA.get(prefix_lower, {}).get("columns", {})
        if cols and col.lower() not in {c.lower() for c in cols}:
            unknown.add(f"{prefix_lower}.{col}")
    return unknown


def check_cost_guard(sql: str) -> Tuple[bool, str]:
    """
    Reject queries on large tables that lack a WHERE or LIMIT clause.

    Returns:
        (is_safe, error_message)
    """
    sql_lower = sql.lower()

    # Extract referenced tables
    referenced = {t.lower() for t in _TABLE_REF_PATTERN.findall(sql)}

    # Check if any large table is referenced without WHERE/LIMIT
    has_where = " where " in sql_lower
    has_limit = " limit " in sql_lower
    has_group = " group by " in sql_lower  # GROUP BY with aggregation is OK

    if has_where or has_limit or has_group:
        return True, ""

    for table_name in referenced:
        schema = OLIST_SCHEMA.get(table_name, {})
        row_count = schema.get("row_count_approx", 0)
        if row_count > 500000:  # Only block very large tables (geolocation=1M)
            return False, (
                f"Table '{table_name}' has ~{row_count:,} rows. "
                "Add a WHERE clause, LIMIT, or GROUP BY to avoid full table scans."
            )

    return True, ""


def sanitize_result(rows: List[dict], max_rows: int) -> Tuple[List[dict], bool]:
    """
    Cap results at max_rows.

    Returns:
        (truncated_rows, was_truncated)
    """
    if len(rows) <= max_rows:
        return rows, False
    return rows[:max_rows], True
