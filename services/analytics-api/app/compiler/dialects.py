"""SQL dialect rules the shared compiler asks for: identifier quoting and time bucketing.

Everything else the compiler emits (ANSI aggregates, `GROUP BY` ordinals, `HAVING`, `LIMIT`, `:pN` named
parameters) is common to the supported engines. Gateways translate `:pN` to the driver's own style.
Identifiers always come from certified contracts, but they are still quoted and checked here, because a
quoted name is the last thing between a contract value and the SQL text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

_FORBIDDEN_IDENTIFIER_CHARS = frozenset(":%;\x00\r\n\t\\")
_MAX_PARTS = 3


class IdentifierError(ValueError):
    """A physical name that cannot be safely quoted for a warehouse dialect."""


@dataclass(frozen=True)
class SQLDialect:
    name: str
    quote_identifier: Callable[[str], str]
    quote_dataset: Callable[[str], str]
    date_trunc: Callable[[str, str], str]


def _postgres_identifier(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _date_trunc(granularity: str, column: str) -> str:
    return f"DATE_TRUNC('{granularity}', {column})"


def _checked(value: str) -> str:
    if not value or not value.strip():
        raise IdentifierError("identifier must not be empty")
    if value != value.strip():
        raise IdentifierError("identifier must not have leading or trailing whitespace")
    if any(char in _FORBIDDEN_IDENTIFIER_CHARS for char in value):
        raise IdentifierError("identifier contains a character that is not allowed")
    return value


def _warehouse_dialect(name: str, quote: Callable[[str], str]) -> SQLDialect:
    def identifier(value: str) -> str:
        return quote(_checked(value))

    def dataset(value: str) -> str:
        parts = value.split(".")
        if not 1 <= len(parts) <= _MAX_PARTS:
            raise IdentifierError("a table name has one to three dot-separated parts")
        return ".".join(identifier(part) for part in parts)

    return SQLDialect(name, identifier, dataset, _date_trunc)


def _snowflake_quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _databricks_quote(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


# PostgreSQL and DuckDB keep their historical, unchecked behavior so existing plans are byte-identical.
POSTGRES = SQLDialect("postgres", _postgres_identifier, _postgres_identifier, _date_trunc)
DUCKDB = SQLDialect("duckdb", _postgres_identifier, _postgres_identifier, _date_trunc)
# Snowflake keeps the case of a quoted name; a contract must therefore state the physical case (usually upper).
SNOWFLAKE = _warehouse_dialect("snowflake", _snowflake_quote)
# Databricks quotes with backticks (double quotes are string literals there); tables may be catalog.schema.table.
DATABRICKS = _warehouse_dialect("databricks", _databricks_quote)
