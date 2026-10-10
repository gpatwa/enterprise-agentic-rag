"""Typed, dialect-neutral analytical intent contract tests."""
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.analytics_intent import AnalyticalIntent

SERVICE_ROOT = Path(__file__).parent.parent


@pytest.fixture
def semantic_contract():
    return SemanticRegistry(SERVICE_ROOT / "semantic_registry").get_certified(
        "olist-commerce", "2026-08-20"
    ).contract


@pytest.fixture
def valid_intent():
    return {
        "query_id": "query-1",
        "tenant_id": "local-demo",
        "dataset_id": "orders",
        "semantic_contract": {
            "contract_id": "olist-commerce",
            "contract_version": "2026-08-20",
        },
        "metrics": [{"metric_id": "delivered_revenue", "alias": "revenue"}],
        "group_by": [
            {"dimension_id": "purchase_time", "time_granularity": "month"},
            {"dimension_id": "order_status"},
        ],
        "time_range": {
            "dimension_id": "purchase_time",
            "start": "2024-01-01T00:00:00Z",
            "end": "2024-01-31T23:59:59Z",
        },
        "filters": [{"field_id": "orders.order_status", "operator": "equals", "values": ["delivered"]}],
        "sort": [
            {"target_kind": "metric", "target_id": "delivered_revenue", "direction": "desc"},
            {"target_kind": "dimension", "target_id": "purchase_time", "direction": "asc"},
        ],
        "limit": 25,
    }


def test_analytical_intent_round_trips_and_validates_against_contract(valid_intent, semantic_contract):
    intent = AnalyticalIntent.model_validate(valid_intent)
    schema = AnalyticalIntent.model_json_schema()

    assert intent.validate_against(semantic_contract) is intent
    assert AnalyticalIntent.model_validate_json(intent.model_dump_json()) == intent
    assert "sql" not in schema["properties"]
    assert {"metrics", "group_by", "time_range", "filters", "sort", "limit"} <= schema["properties"].keys()


@pytest.mark.parametrize(
    "mutate, expected_error",
    [
        (lambda value: value.update(sql="SELECT * FROM olist_orders"), "Extra inputs are not permitted"),
        (lambda value: value["metrics"].append({"metric_id": "delivered_revenue"}), "metric IDs must be unique"),
        (lambda value: value["sort"][0].update(target_id="order_status"), "not selected by the intent"),
        (lambda value: value["time_range"].update(start="2024-02-01T00:00:00Z", end="2024-01-01T00:00:00Z"), "start must be before"),
    ],
)
def test_analytical_intent_rejects_invalid_shape(valid_intent, mutate, expected_error):
    mutate(valid_intent)

    with pytest.raises(ValidationError, match=expected_error):
        AnalyticalIntent.model_validate(valid_intent)


def test_analytical_intent_rejects_unknown_semantic_ids(valid_intent, semantic_contract):
    valid_intent["metrics"][0]["metric_id"] = "unknown_metric"
    valid_intent["sort"][0]["target_id"] = "unknown_metric"
    intent = AnalyticalIntent.model_validate(valid_intent)

    with pytest.raises(ValueError, match="unknown intent metric"):
        intent.validate_against(semantic_contract)


def test_analytical_intent_requires_a_temporal_dimension_for_time_range(valid_intent, semantic_contract):
    valid_intent["time_range"]["dimension_id"] = "order_status"
    intent = AnalyticalIntent.model_validate(valid_intent)

    with pytest.raises(ValueError, match="temporal dimension"):
        intent.validate_against(semantic_contract)
