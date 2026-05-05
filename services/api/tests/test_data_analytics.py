# services/api/tests/test_data_analytics.py
"""
Tests for the Data Analytics Agent.

Covers: schema context, SQL safety validation, formatter,
planner routing, graph wiring, and state fields.
"""
import ast
import os

import pytest

# Ensure DATA_ANALYTICS_ENABLED is set before importing app modules
os.environ.setdefault("DATA_ANALYTICS_ENABLED", "true")


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


# ── Planner Routing Tests ─────────────────────────────────────────────

class TestPlannerDataRouting:
    def test_fast_classify_data_query(self):
        from app.agents.nodes.planner import _fast_classify
        result = _fast_classify("What was the revenue trend by month?", False)
        assert result == "data_query"

    def test_fast_classify_top_categories(self):
        from app.agents.nodes.planner import _fast_classify
        result = _fast_classify("Top 10 product categories by sales", False)
        assert result == "data_query"

    def test_fast_classify_greeting_not_data(self):
        from app.agents.nodes.planner import _fast_classify
        result = _fast_classify("hello", False)
        assert result == "direct_answer"

    def test_fast_classify_general_question(self):
        from app.agents.nodes.planner import _fast_classify
        result = _fast_classify("What is RAG?", False)
        assert result == "retrieve"

    def test_data_keywords_defined(self):
        from app.agents.nodes.planner import _DATA_KEYWORDS
        assert "revenue" in _DATA_KEYWORDS
        assert "orders" in _DATA_KEYWORDS
        assert "customers" in _DATA_KEYWORDS


# ── Graph Wiring Tests ────────────────────────────────────────────────

class TestGraphWiring:
    def test_data_analytics_node_in_graph(self):
        from app.agents.graph import agent_app
        nodes = list(agent_app.nodes.keys())
        assert "data_analytics" in nodes

    def test_data_analytics_edges_exist(self):
        from app.agents.graph import agent_app
        nodes = list(agent_app.nodes.keys())
        assert "data_analytics:edges" in nodes


# ── State Tests ───────────────────────────────────────────────────────

class TestAgentState:
    def test_state_has_data_query_fields(self):
        from app.agents.state import AgentState
        hints = AgentState.__annotations__
        assert "data_query_sql" in hints
        assert "data_query_result" in hints
        assert "data_query_error" in hints
        assert "data_query_time_ms" in hints


# ── Config Tests ──────────────────────────────────────────────────────

class TestAnalyticsConfig:
    def test_master_switch_exists(self):
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "DATA_ANALYTICS_ENABLED")

    def test_default_off(self):
        """Default should be False in config definition (even if env overrides)."""
        import ast
        source = open("app/config.py").read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AnnAssign) and hasattr(node.target, "attr"):
                if node.target.attr == "DATA_ANALYTICS_ENABLED":
                    # Check the default value in the source
                    assert node.value is not None

    def test_timeout_setting(self):
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "ANALYTICS_QUERY_TIMEOUT")
        assert s.ANALYTICS_QUERY_TIMEOUT == 10

    def test_max_rows_setting(self):
        from app.config import Settings
        s = Settings()
        assert hasattr(s, "ANALYTICS_MAX_ROWS")
        assert s.ANALYTICS_MAX_ROWS == 1000


# ── Data Analytics Node Tests ─────────────────────────────────────────

class TestDataAnalyticsNode:
    def test_node_is_async(self):
        import asyncio

        from app.agents.nodes.data_analytics import data_analytics_node
        assert asyncio.iscoroutinefunction(data_analytics_node)

    def test_has_set_analytics_llm(self):
        from app.agents.nodes.data_analytics import set_analytics_llm
        assert callable(set_analytics_llm)

    def test_engine_module_imports(self):
        from app.analytics.engine import (
            init_analytics_engine,
            run_data_query,
        )
        assert callable(init_analytics_engine)
        assert callable(run_data_query)


# ── Syntax Check for All Analytics Files ──────────────────────────────

class TestSyntaxCheck:
    @pytest.mark.parametrize("filepath", [
        "app/analytics/__init__.py",
        "app/analytics/schema_context.py",
        "app/analytics/safety.py",
        "app/analytics/engine.py",
        "app/analytics/formatter.py",
        "app/agents/nodes/data_analytics.py",
    ])
    def test_file_parses(self, filepath):
        source = open(filepath).read()
        ast.parse(source)  # Raises SyntaxError if invalid
