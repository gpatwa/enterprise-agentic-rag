"""Dialect-aware read-only query shape validation for execution gateways.

Distinct from `app.analytics.safety`, which is bound to the legacy Olist schema:
this validator takes the physical-table allowlist from the caller (derived from
the certified contract) and is the last guard before a driver sees SQL.
"""

from __future__ import annotations

from typing import Iterable

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.execution.gateway import QueryRejected

_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
_FORBIDDEN = tuple(
    node
    for node in (
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
        exp.Copy,
        exp.Set,
        exp.Use,
        exp.Pragma,
        exp.Attach,
        exp.Detach,
        exp.Into,
        exp.Lock,
    )
    if node is not None
)
DEFAULT_ALLOWED_FUNCTIONS = frozenset(
    {
        "abs",
        "avg",
        "case",
        "cast",
        "ceil",
        "coalesce",
        "count",
        "date_trunc",
        "extract",
        "floor",
        "greatest",
        "if",
        "least",
        "lower",
        "max",
        "min",
        "nullif",
        "round",
        "sum",
        "timestamp_trunc",
        "trim",
        "upper",
    }
)


def validate_read_only_sql(
    sql: str,
    *,
    dialect: str,
    allowed_tables: Iterable[str],
    allowed_functions: Iterable[str] = DEFAULT_ALLOWED_FUNCTIONS,
    case_sensitive_quoted: bool = False,
) -> exp.Expression:
    """Return the parsed tree for one read-only query or raise `QueryRejected`.

    By default table names compare case-insensitively (right for DuckDB). With `case_sensitive_quoted` (PostgreSQL), a quoted
    name must equal an allowlist entry exactly, because `"Orders"` and `orders` are different tables there; unquoted names are
    folded to lower case, as the server does, and `allowed_tables` entries are then taken as exact physical names.
    """
    try:
        statements = sqlglot.parse(sql, read=dialect)
    except SqlglotError as exc:
        raise QueryRejected("query could not be parsed") from exc
    if len(statements) != 1 or statements[0] is None:
        raise QueryRejected("exactly one statement is required")
    tree = statements[0]
    if not isinstance(tree, _ROOTS):
        raise QueryRejected("only read-only queries are allowed")
    if any(isinstance(node, _FORBIDDEN) for node in tree.walk()):
        raise QueryRejected("only read-only queries are allowed")

    permitted_functions = {name.lower() for name in allowed_functions}
    for function in tree.find_all(exp.Func):
        if isinstance(function, (exp.Binary, exp.Unary)):  # operators (AND, +, NOT) are not calls
            continue
        name = function.name if isinstance(function, exp.Anonymous) else function.sql_name()
        if name.lower() not in permitted_functions:
            raise QueryRejected(f"function is not allowed: {name.lower()}")

    def fold(identifier: exp.Expression) -> str:
        name = identifier.name
        return name if case_sensitive_quoted and getattr(identifier, "quoted", False) else name.lower()

    cte_names = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.args.get("alias")
        if alias is not None and alias.this is not None:
            cte_names.add(fold(alias.this))
    permitted_tables = set(allowed_tables) if case_sensitive_quoted else {name.lower() for name in allowed_tables}
    for table in tree.find_all(exp.Table):
        if isinstance(table.this, exp.Func):
            raise QueryRejected("table-valued functions are not allowed")
        parts = (table.args.get("catalog"), table.args.get("db"), table.this)
        qualified = ".".join(fold(part) for part in parts if part is not None and part.name)
        if qualified in cte_names and not table.db:
            continue
        if qualified not in permitted_tables:
            raise QueryRejected(f"table is not allowed: {qualified}")
    return tree
