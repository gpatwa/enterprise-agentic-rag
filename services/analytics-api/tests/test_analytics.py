# services/analytics-api/tests/test_analytics.py
"""
Tests for the Data Analytics Agent.

Covers schema context, SQL safety, formatting, shared contracts, and the
standalone service boundary.
"""
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

# ── Schema Context Tests ──────────────────────────────────────────────

class TestSchemaContext:
    def test_all_eight_tables_defined(self):
        from app.analytics.schema_context import OLIST_SCHEMA
        assert len(OLIST_SCHEMA) == 8
        expected = {
            "olist_customers", "olist_orders", "olist_order_items",
            "olist_order_payments", "olist_order_reviews",
            "olist_products", "olist_sellers", "olist_geolocation",
        }
        assert set(OLIST_SCHEMA.keys()) == expected

    def test_get_all_table_names(self):
        from app.analytics.schema_context import get_all_table_names
        names = get_all_table_names()
        assert isinstance(names, list)
        assert len(names) == 8
        assert "olist_orders" in names

    def test_build_schema_prompt_returns_string(self):
        from app.analytics.schema_context import build_schema_prompt
        prompt = build_schema_prompt("What was the revenue by month?")
        assert isinstance(prompt, str)
        assert len(prompt) > 100

    def test_build_schema_prompt_includes_relevant_tables(self):
        from app.analytics.schema_context import build_schema_prompt
        prompt = build_schema_prompt("revenue by payment method")
        assert "olist_order_payments" in prompt
        assert "payment_value" in prompt

    def test_build_schema_prompt_fallback_to_core_tables(self):
        from app.analytics.schema_context import build_schema_prompt
        prompt = build_schema_prompt("xyzzy nonsense query")
        # Should fall back to core tables
        assert "olist_orders" in prompt

    def test_common_metrics_defined(self):
        from app.analytics.schema_context import COMMON_METRICS
        assert "revenue" in COMMON_METRICS
        assert "total_orders" in COMMON_METRICS
        assert "average_review_score" in COMMON_METRICS

    def test_table_relationships_defined(self):
        from app.analytics.schema_context import TABLE_RELATIONSHIPS
        assert isinstance(TABLE_RELATIONSHIPS, list)
        assert len(TABLE_RELATIONSHIPS) > 0
        # Check structure
        rel = TABLE_RELATIONSHIPS[0]
        assert "from" in rel and "to" in rel and "type" in rel

    def test_every_table_has_keywords(self):
        from app.analytics.schema_context import OLIST_SCHEMA
        for table_name, info in OLIST_SCHEMA.items():
            assert "keywords" in info, f"{table_name} missing keywords"
            assert len(info["keywords"]) > 0, f"{table_name} has empty keywords"


# ── SQL Safety Tests ──────────────────────────────────────────────────

class TestSQLSafety:
    @pytest.mark.parametrize(
        "unsafe_sql",
        [
            "DROP TABLE olist_orders",
            "DELETE FROM olist_orders WHERE 1=1",
            "INSERT INTO olist_orders VALUES (1)",
            "UPDATE olist_orders SET status='hacked'",
            "TRUNCATE TABLE olist_orders",
            "GRANT ALL ON olist_orders TO public",
            "ALTER TABLE olist_orders DROP COLUMN customer_id",
            "CREATE TABLE x AS SELECT * FROM olist_orders",
            "SELECT pg_sleep(60)",
            "COPY olist_orders TO '/tmp/leak'",
            "SELECT 1; DROP TABLE olist_orders",
            "SELECT * FROM users_passwords",
        ],
    )
    def test_rejects_malicious_sql(self, unsafe_sql):
        from app.analytics.safety import validate_sql

        ok, error = validate_sql(unsafe_sql)
        assert ok is False, f"Should reject {unsafe_sql!r}: {error}"

    def test_valid_select(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("SELECT COUNT(*) FROM olist_orders")
        assert ok is True
        assert err == ""

    def test_valid_with_cte(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("WITH t AS (SELECT * FROM olist_orders) SELECT COUNT(*) FROM t")
        assert ok is True

    def test_reject_drop(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("DROP TABLE olist_orders")
        assert ok is False
        assert "SELECT" in err

    def test_reject_delete(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("DELETE FROM olist_orders WHERE 1=1")
        assert ok is False

    def test_reject_insert(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("INSERT INTO olist_orders VALUES (1)")
        assert ok is False

    def test_reject_unknown_table(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("SELECT * FROM secret_table")
        assert ok is False
        assert "Unknown tables" in err

    def test_reject_unknown_qualified_column(self):
        from app.analytics.safety import validate_sql

        ok, error = validate_sql(
            "SELECT olist_orders.password FROM olist_orders LIMIT 5"
        )
        assert ok is False
        assert "olist_orders.password" in error

    def test_allow_known_qualified_column(self):
        from app.analytics.safety import validate_sql

        ok, error = validate_sql(
            "SELECT olist_orders.order_status FROM olist_orders LIMIT 5"
        )
        assert ok is True, error

    def test_reject_multiple_statements(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("SELECT 1; DROP TABLE olist_orders")
        assert ok is False

    def test_reject_pg_sleep(self):
        from app.analytics.safety import validate_sql
        ok, err = validate_sql("SELECT pg_sleep(10) FROM olist_orders")
        assert ok is False
        assert "pg_sleep" in err

    def test_cost_guard_rejects_full_scan_on_large_table(self):
        from app.analytics.safety import check_cost_guard
        ok, err = check_cost_guard("SELECT * FROM olist_geolocation")
        assert ok is False
        assert "1,000,163" in err

    def test_cost_guard_allows_with_where(self):
        from app.analytics.safety import check_cost_guard
        ok, err = check_cost_guard(
            "SELECT * FROM olist_geolocation WHERE geolocation_state = 'SP'"
        )
        assert ok is True

    def test_cost_guard_allows_with_group_by(self):
        from app.analytics.safety import check_cost_guard
        ok, err = check_cost_guard(
            "SELECT geolocation_state, COUNT(*) FROM olist_geolocation GROUP BY 1"
        )
        assert ok is True

    def test_sanitize_result_truncates(self):
        from app.analytics.safety import sanitize_result
        rows = [{"a": i} for i in range(100)]
        result, truncated = sanitize_result(rows, max_rows=10)
        assert len(result) == 10
        assert truncated is True

    def test_sanitize_result_no_truncation(self):
        from app.analytics.safety import sanitize_result
        rows = [{"a": i} for i in range(5)]
        result, truncated = sanitize_result(rows, max_rows=10)
        assert len(result) == 5
        assert truncated is False


# ── Formatter Tests ───────────────────────────────────────────────────

class TestFormatter:
    def test_format_as_table_html(self):
        from app.analytics.formatter import format_as_table_html
        html = format_as_table_html(
            ["name", "value"],
            [{"name": "A", "value": 100}, {"name": "B", "value": 200}],
        )
        assert '<table class="data-table">' in html
        assert "<th>" in html
        assert "100" in html

    def test_format_as_table_html_empty(self):
        from app.analytics.formatter import format_as_table_html
        html = format_as_table_html([], [])
        assert "No results" in html

    def test_format_for_llm_context(self):
        from app.analytics.formatter import format_for_llm_context
        md = format_for_llm_context(
            ["month", "revenue"],
            [{"month": "2024-01", "revenue": 1000}],
        )
        assert "month" in md
        assert "revenue" in md
        assert "2024-01" in md

    def test_suggest_chart_spec_line(self):
        from app.analytics.formatter import suggest_chart_spec
        spec = suggest_chart_spec(
            ["month", "revenue"],
            [
                {"month": "2024-01", "revenue": 1000},
                {"month": "2024-02", "revenue": 2000},
            ],
            "revenue by month",
        )
        assert spec is not None
        assert spec["mark"]["type"] == "line"

    def test_suggest_chart_spec_bar(self):
        from app.analytics.formatter import suggest_chart_spec
        spec = suggest_chart_spec(
            ["category", "count"],
            [
                {"category": "A", "count": 10},
                {"category": "B", "count": 20},
            ],
            "orders by category",
        )
        assert spec is not None
        assert spec["mark"] == "bar"

    def test_suggest_chart_spec_none_for_single_row(self):
        from app.analytics.formatter import suggest_chart_spec
        spec = suggest_chart_spec(
            ["total"],
            [{"total": 42}],
            "total orders",
        )
        assert spec is None

    def test_format_numbers_with_commas(self):
        from app.analytics.formatter import format_as_table_html
        html = format_as_table_html(
            ["revenue"],
            [{"revenue": 1234567.89}],
        )
        assert "1,234,567.89" in html


# ── Config Tests ──────────────────────────────────────────────────────

class TestAnalyticsConfig:
    def test_product_settings_are_owned_by_service(self):
        from app.config import Settings
        settings = Settings(_env_file=None)
        assert settings.ANALYTICS_LLM_MODEL == "gpt-4o-mini"
        assert settings.database_url is None

    def test_timeout_setting(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.ANALYTICS_QUERY_TIMEOUT == 10

    def test_max_rows_setting(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.ANALYTICS_MAX_ROWS == 1000


# ── Shared Contract Tests ─────────────────────────────────────────────

class TestSharedContracts:
    def test_query_contract_defaults(self):
        from packages.platform_contracts.analytics import AnalyticsQueryRequest

        request = AnalyticsQueryRequest(query="Revenue by month")
        assert request.dataset == "olist"
        assert request.tenant_id == "local-demo"

    def test_query_contract_rejects_empty_query(self):
        from packages.platform_contracts.analytics import AnalyticsQueryRequest

        with pytest.raises(ValidationError):
            AnalyticsQueryRequest(query="")


# ── Standalone Service Tests ──────────────────────────────────────────

class TestAnalyticsService:
    @pytest.mark.asyncio
    async def test_demo_mode_is_local_and_deterministic(self):
        from app.config import Settings
        from app.service import AnalyticsService
        from packages.platform_contracts.analytics import AnalyticsQueryRequest

        service = AnalyticsService(
            Settings(_env_file=None, ANALYTICS_DEMO_MODE=True)
        )
        response = await service.query(
            AnalyticsQueryRequest(query="Revenue trend by month")
        )

        assert response.status == "succeeded"
        assert response.row_count == 6
        assert response.chart_spec is not None
        assert response.execution_time_ms == 18

    @pytest.mark.asyncio
    async def test_query_returns_versioned_contract(self):
        from app.config import Settings
        from app.service import AnalyticsService
        from packages.platform_contracts.analytics import AnalyticsQueryRequest

        service = AnalyticsService(Settings(_env_file=None))

        async def fake_run(_: str) -> dict:
            return {
                "sql": "SELECT COUNT(*) AS total_orders FROM olist_orders",
                "columns": ["total_orders"],
                "rows": [{"total_orders": 42}],
                "row_count": 1,
                "time_ms": 7,
                "error": "",
                "truncated": False,
            }

        service.engine.run = fake_run
        response = await service.query(
            AnalyticsQueryRequest(query="How many orders were placed?")
        )

        assert response.contract_version == "v1"
        assert response.status == "succeeded"
        assert response.row_count == 1
        assert response.sql.startswith("SELECT")

    def test_schema_is_product_owned(self):
        from app.config import Settings
        from app.service import AnalyticsService

        response = AnalyticsService(Settings(_env_file=None)).schema("olist")
        assert "olist_orders" in response.tables
        assert "revenue" in response.metrics


class TestAnalyticsEngine:
    def test_engine_has_explicit_dependencies(self):
        from app.analytics.engine import AnalyticsEngine
        from app.config import Settings

        class FakeLLM:
            async def chat_completion(self, messages, temperature=0.0):
                return "SELECT COUNT(*) FROM olist_orders"

        engine = AnalyticsEngine(Settings(_env_file=None), FakeLLM())
        assert engine.config.ANALYTICS_QUERY_TIMEOUT == 10

    def test_postgres_engine_enforces_read_only_transactions(self):
        import inspect

        from app.analytics import engine

        source = inspect.getsource(engine)
        assert "default_transaction_read_only=on" in source
        assert "statement_timeout" in source

    @pytest.mark.asyncio
    async def test_generate_sql_validates_llm_output(self):
        from app.analytics.engine import AnalyticsEngine
        from app.config import Settings

        class UnsafeLLM:
            async def chat_completion(self, messages, temperature=0.0):
                return "DROP TABLE olist_orders"

        engine = AnalyticsEngine(Settings(_env_file=None), UnsafeLLM())
        with pytest.raises(ValueError, match="SQL validation failed"):
            await engine.generate_sql("Delete the orders")


# ── Syntax Check for All Analytics Files ──────────────────────────────

class TestSyntaxCheck:
    @pytest.mark.parametrize("filepath", [
        "app/analytics/__init__.py",
        "app/analytics/schema_context.py",
        "app/analytics/safety.py",
        "app/analytics/engine.py",
        "app/analytics/formatter.py",
        "app/config.py",
        "app/llm.py",
        "app/service.py",
        "app/main.py",
    ])
    def test_file_parses(self, filepath):
        source = (Path(__file__).parent.parent / filepath).read_text()
        ast.parse(source)  # Raises SyntaxError if invalid
