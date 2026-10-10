"""Adversarial and valid PostgreSQL cases for AST-based SQL safety validation."""
import pytest

from app.analytics.safety import validate_sql


@pytest.mark.parametrize(
    "sql, category",
    [
        ("WITH changed AS (DELETE FROM olist_orders RETURNING *) SELECT * FROM changed", "SQL_NOT_READ_ONLY"),
        ("SELECT 1; DROP TABLE olist_orders", "SQL_MULTIPLE_STATEMENTS"),
        ("SELECT * FROM information_schema.tables", "SQL_UNKNOWN_TABLE"),
        ("SELECT * FROM pg_catalog.pg_tables", "SQL_UNKNOWN_TABLE"),
        ("SELECT pg_sleep(1)", "SQL_DISALLOWED_FUNCTION"),
        ("SELECT * FROM generate_series(1, 5)", "SQL_DISALLOWED_FUNCTION"),
        ("SELECT FROM", "SQL_PARSE_ERROR"),
        ('SELECT * FROM "other_schema"."orders"', "SQL_UNKNOWN_TABLE"),
    ],
)
def test_ast_validator_rejects_adversarial_queries(sql, category):
    safe, error = validate_sql(sql)

    assert safe is False
    assert error.startswith(f"[{category}]")


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT COUNT(*) FROM olist_orders",
        "SELECT o.order_status, COUNT(*) FROM olist_orders o GROUP BY o.order_status",
        "WITH paid AS (SELECT order_id, SUM(payment_value) AS revenue FROM olist_order_payments GROUP BY order_id) SELECT AVG(paid.revenue) FROM paid",
        "SELECT order_id, ROW_NUMBER() OVER (ORDER BY order_id) AS rank FROM olist_orders",
        "SELECT order_id FROM olist_orders UNION SELECT order_id FROM olist_order_items",
        "SELECT q.order_id FROM (SELECT order_id FROM olist_orders) q",
    ],
)
def test_ast_validator_accepts_supported_read_only_queries(sql):
    safe, error = validate_sql(sql)

    assert safe is True, error


def test_ast_validator_resolves_physical_table_aliases_but_not_projected_aliases():
    safe, error = validate_sql("SELECT o.password FROM olist_orders o")
    assert safe is False
    assert "olist_orders.password" in error

    safe, error = validate_sql(
        "WITH order_ids AS (SELECT order_id FROM olist_orders) SELECT order_id AS derived_id FROM order_ids"
    )
    assert safe is True, error
