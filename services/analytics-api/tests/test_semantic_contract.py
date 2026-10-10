"""Contract validation for the catalog-neutral analytics semantic model."""
from copy import deepcopy

import pytest
from pydantic import ValidationError

from packages.platform_contracts.semantic import SemanticContract, SemanticMetric


@pytest.fixture
def valid_contract():
    return {
        "id": "commerce-core",
        "tenant_id": "tenant-a",
        "domain": "commerce",
        "version": "2026-08-20",
        "owners": [{"id": "team.data", "display_name": "Data Team", "owner_type": "team"}],
        "datasets": [
            {
                "id": "orders",
                "display_name": "Orders",
                "source_asset_id": "catalog.orders",
                "physical_name": "orders",
                "description": "One row per order",
                "owner_ids": ["team.data"],
            },
            {
                "id": "order_items",
                "display_name": "Order items",
                "source_asset_id": "catalog.order_items",
                "physical_name": "order_items",
                "description": "One row per item",
                "owner_ids": ["team.data"],
            },
        ],
        "fields": [
            {"id": "orders.order_id", "dataset_id": "orders", "physical_name": "order_id", "data_type": "string"},
            {"id": "orders.status", "dataset_id": "orders", "physical_name": "status", "data_type": "string"},
            {"id": "orders.payment_total", "dataset_id": "orders", "physical_name": "payment_total", "data_type": "decimal"},
            {"id": "items.order_id", "dataset_id": "order_items", "physical_name": "order_id", "data_type": "string"},
            {"id": "items.price", "dataset_id": "order_items", "physical_name": "price", "data_type": "decimal"},
        ],
        "entities": [
            {
                "id": "order",
                "dataset_id": "orders",
                "grain": {"kind": "order", "key_field_ids": ["orders.order_id"]},
                "owner_ids": ["team.data"],
            }
        ],
        "dimensions": [
            {
                "id": "order_status",
                "dataset_id": "orders",
                "field_id": "orders.status",
                "entity_id": "order",
                "dimension_type": "categorical",
                "owner_ids": ["team.data"],
            }
        ],
        "filters": [
            {
                "id": "delivered_orders",
                "dataset_id": "orders",
                "field_id": "orders.status",
                "operator": "equals",
                "value_source": "literal",
                "literal_value": "delivered",
            }
        ],
        "metrics": [
            {
                "id": "delivered_revenue",
                "dataset_id": "orders",
                "aggregation": "sum",
                "measure_field_id": "orders.payment_total",
                "grain": {"kind": "order", "key_field_ids": ["orders.order_id"]},
                "required_filter_ids": ["delivered_orders"],
                "certification": "certified",
                "owner_ids": ["team.data"],
            }
        ],
        "joins": [
            {
                "id": "items_to_orders",
                "from_dataset_id": "order_items",
                "to_dataset_id": "orders",
                "from_field_ids": ["items.order_id"],
                "to_field_ids": ["orders.order_id"],
                "cardinality": "many_to_one",
                "approved": True,
            }
        ],
        "policies": [
            {
                "id": "commerce_internal",
                "target_ids": ["delivered_revenue"],
                "classification": "internal",
                "allowed_purposes": ["analytics"],
                "required_filter_ids": ["delivered_orders"],
                "owner_ids": ["team.data"],
            }
        ],
    }


def test_semantic_contract_round_trips_and_generates_json_schema(valid_contract):
    contract = SemanticContract.model_validate(valid_contract)
    schema = SemanticContract.model_json_schema()

    assert contract.metrics[0].certification == "certified"
    assert SemanticContract.model_validate_json(contract.model_dump_json()) == contract
    assert "datasets" in schema["properties"]
    assert "metrics" in schema["properties"]
    assert "joins" in schema["properties"]


@pytest.mark.parametrize(
    "mutate, expected_error",
    [
        (
            lambda value: value["datasets"][0].update(owner_ids=["missing.owner"]),
            "unknown dataset owner",
        ),
        (
            lambda value: value["metrics"][0].update(measure_field_id="items.price"),
            "metric measure field items.price must belong to dataset orders",
        ),
        (
            lambda value: value["joins"][0].update(to_field_ids=["orders.order_id", "orders.status"]),
            "join field lists must have the same length",
        ),
        (
            lambda value: value["policies"][0].update(target_ids=["missing.metric"]),
            "unknown policy target",
        ),
    ],
)
def test_semantic_contract_rejects_invalid_references(valid_contract, mutate, expected_error):
    contract = deepcopy(valid_contract)
    mutate(contract)

    with pytest.raises(ValidationError, match=expected_error):
        SemanticContract.model_validate(contract)


def test_semantic_contract_rejects_duplicate_ids(valid_contract):
    contract = deepcopy(valid_contract)
    contract["datasets"].append(deepcopy(contract["datasets"][0]))

    with pytest.raises(ValidationError, match="duplicate dataset IDs"):
        SemanticContract.model_validate(contract)


def test_semantic_contract_rejects_ambiguous_ids_across_asset_types(valid_contract):
    contract = deepcopy(valid_contract)
    contract["dimensions"][0]["id"] = "orders"

    with pytest.raises(ValidationError, match="semantic asset IDs must be unique"):
        SemanticContract.model_validate(contract)


@pytest.mark.parametrize(
    "metric, expected_error",
    [
        (
            {
                "id": "conversion",
                "dataset_id": "orders",
                "aggregation": "ratio",
                "grain": {"kind": "order", "key_field_ids": ["orders.order_id"]},
                "owner_ids": ["team.data"],
            },
            "ratio metrics require",
        ),
        (
            {
                "id": "revenue",
                "dataset_id": "orders",
                "aggregation": "sum",
                "grain": {"kind": "order", "key_field_ids": ["orders.order_id"]},
                "owner_ids": ["team.data"],
            },
            "sum metrics require measure_field_id",
        ),
        (
            {
                "id": "unique_orders",
                "dataset_id": "orders",
                "aggregation": "count_distinct",
                "grain": {"kind": "order", "key_field_ids": ["orders.order_id"]},
                "owner_ids": ["team.data"],
            },
            "count_distinct metrics require measure_field_id",
        ),
    ],
)
def test_metric_formula_shape_is_validated(metric, expected_error):
    with pytest.raises(ValidationError, match=expected_error):
        SemanticMetric.model_validate(metric)
