"""Deterministic SQL golden tests for the narrow PostgreSQL compiler spike."""
from copy import deepcopy

import pytest

from app.compiler import CompilationError, PostgreSQLCompiler
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract


@pytest.fixture
def compiler_contract():
    return SemanticContract.model_validate(
        {
            "id": "sales-core",
            "tenant_id": "tenant-a",
            "domain": "sales",
            "version": "v1",
            "owners": [{"id": "team.data", "display_name": "Data", "owner_type": "team"}],
            "datasets": [
                {
                    "id": "orders",
                    "display_name": "Orders",
                    "source_asset_id": "warehouse.orders",
                    "physical_name": "sales_orders",
                    "description": "One row per order",
                    "owner_ids": ["team.data"],
                }
            ],
            "fields": [
                {"id": "orders.id", "dataset_id": "orders", "physical_name": "id", "data_type": "string"},
                {"id": "orders.amount", "dataset_id": "orders", "physical_name": "amount", "data_type": "decimal"},
                {"id": "orders.status", "dataset_id": "orders", "physical_name": "status", "data_type": "string"},
                {"id": "orders.created_at", "dataset_id": "orders", "physical_name": "created_at", "data_type": "timestamp"},
            ],
            "dimensions": [
                {"id": "status", "dataset_id": "orders", "field_id": "orders.status", "dimension_type": "categorical", "owner_ids": ["team.data"]},
                {"id": "created_at", "dataset_id": "orders", "field_id": "orders.created_at", "dimension_type": "temporal", "owner_ids": ["team.data"]},
            ],
            "metrics": [
                {
                    "id": "revenue",
                    "dataset_id": "orders",
                    "aggregation": "sum",
                    "measure_field_id": "orders.amount",
                    "grain": {"kind": "order", "key_field_ids": ["orders.id"]},
                    "certification": "certified",
                    "owner_ids": ["team.data"],
                }
            ],
        }
    )


@pytest.fixture
def compiler_intent():
    return AnalyticalIntent.model_validate(
        {
            "query_id": "q-1",
            "tenant_id": "tenant-a",
            "dataset_id": "orders",
            "semantic_contract": {"contract_id": "sales-core", "contract_version": "v1"},
            "metrics": [{"metric_id": "revenue"}],
            "group_by": [{"dimension_id": "created_at", "time_granularity": "month"}],
            "time_range": {
                "dimension_id": "created_at",
                "start": "2024-01-01T00:00:00Z",
                "end": "2024-01-31T23:59:59Z",
            },
            "filters": [{"field_id": "orders.status", "operator": "equals", "values": ["paid"]}],
            "sort": [{"target_kind": "metric", "target_id": "revenue", "direction": "desc"}],
            "limit": 25,
        }
    )


def test_compiler_produces_deterministic_parameterized_postgres_sql(compiler_contract, compiler_intent):
    compiler = PostgreSQLCompiler()

    compiled = compiler.compile(compiler_intent, compiler_contract)

    assert compiled.sql == "\n".join(
        [
            "SELECT DATE_TRUNC('month', d0.\"created_at\") AS dimension_0, SUM(d0.\"amount\") AS metric_0",
            "FROM \"sales_orders\" AS d0",
            "WHERE d0.\"status\" = :p0 AND d0.\"created_at\" >= :p1 AND d0.\"created_at\" <= :p2",
            "GROUP BY 1",
            "ORDER BY metric_0 DESC",
            "LIMIT 25",
        ]
    )
    assert compiled.parameters == {
        "p0": "paid",
        "p1": compiler_intent.time_range.start,
        "p2": compiler_intent.time_range.end,
    }
    assert compiler.compile(compiler_intent, compiler_contract) == compiled


def test_compiler_requires_policy_context_for_required_filters(compiler_contract, compiler_intent):
    contract_data = compiler_contract.model_dump()
    contract_data["filters"] = [
        {
            "id": "tenant_scope",
            "dataset_id": "orders",
            "field_id": "orders.status",
            "operator": "equals",
            "value_source": "request_context",
        }
    ]
    contract_data["metrics"][0]["required_filter_ids"] = ["tenant_scope"]
    contract = SemanticContract.model_validate(contract_data)

    with pytest.raises(CompilationError, match="missing policy value"):
        PostgreSQLCompiler().compile(compiler_intent, contract)

    compiled = PostgreSQLCompiler().compile(
        compiler_intent, contract, policy_values={"tenant_scope": "tenant-a"}
    )
    assert compiled.parameters["p0"] == "tenant-a"
    assert compiled.applied_filter_ids == ("tenant_scope",)


def test_compiler_injects_literal_policy_filters_without_caller_values(compiler_contract, compiler_intent):
    contract_data = compiler_contract.model_dump()
    contract_data["filters"] = [
        {
            "id": "paid_only",
            "dataset_id": "orders",
            "field_id": "orders.status",
            "operator": "equals",
            "value_source": "literal",
            "literal_value": "paid",
        }
    ]
    contract_data["policies"] = [
        {
            "id": "revenue_policy",
            "target_ids": ["revenue"],
            "classification": "internal",
            "allowed_purposes": ["analytics"],
            "required_filter_ids": ["paid_only"],
            "owner_ids": ["team.data"],
        }
    ]
    contract = SemanticContract.model_validate(contract_data)

    compiled = PostgreSQLCompiler().compile(compiler_intent, contract)

    assert compiled.parameters["p0"] == "paid"
    assert compiled.applied_filter_ids == ("paid_only",)


def test_compiler_rejects_ratio_metrics_until_the_expression_is_governed(compiler_contract, compiler_intent):
    contract_data = deepcopy(compiler_contract.model_dump())
    contract_data["metrics"] = [
        {
            "id": "conversion",
            "dataset_id": "orders",
            "aggregation": "ratio",
            "numerator_metric_id": "conversion",
            "denominator_metric_id": "conversion",
            "grain": {"kind": "order", "key_field_ids": ["orders.id"]},
            "owner_ids": ["team.data"],
        }
    ]
    contract = SemanticContract.model_validate(contract_data)
    intent_data = compiler_intent.model_dump()
    intent_data["metrics"] = [{"metric_id": "conversion"}]
    intent_data["sort"] = [{"target_kind": "metric", "target_id": "conversion", "direction": "desc"}]
    intent = AnalyticalIntent.model_validate(intent_data)

    with pytest.raises(CompilationError, match="ratio metrics are not supported"):
        PostgreSQLCompiler().compile(intent, contract)
