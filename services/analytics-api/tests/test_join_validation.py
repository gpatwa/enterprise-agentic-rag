"""EA-015 join-cardinality and aggregation-grain tests."""
from copy import deepcopy

import pytest

from app.compiler import JoinValidationError, validate_join_safety
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract


def contract_with_join(cardinality="many_to_one", approved=True):
    return SemanticContract.model_validate(
        {
            "id": "commerce",
            "tenant_id": "tenant-a",
            "domain": "commerce",
            "version": "v1",
            "owners": [{"id": "team", "display_name": "Team", "owner_type": "team"}],
            "datasets": [
                {"id": "items", "display_name": "Items", "source_asset_id": "items", "physical_name": "items", "description": "Items", "owner_ids": ["team"]},
                {"id": "orders", "display_name": "Orders", "source_asset_id": "orders", "physical_name": "orders", "description": "Orders", "owner_ids": ["team"]},
            ],
            "fields": [
                {"id": "items.order_id", "dataset_id": "items", "physical_name": "order_id", "data_type": "string"},
                {"id": "items.price", "dataset_id": "items", "physical_name": "price", "data_type": "decimal"},
                {"id": "orders.order_id", "dataset_id": "orders", "physical_name": "order_id", "data_type": "string"},
                {"id": "orders.status", "dataset_id": "orders", "physical_name": "status", "data_type": "string"},
            ],
            "dimensions": [{"id": "order_status", "dataset_id": "orders", "field_id": "orders.status", "dimension_type": "categorical", "owner_ids": ["team"]}],
            "metrics": [{"id": "item_gmv", "dataset_id": "items", "aggregation": "sum", "measure_field_id": "items.price", "grain": {"kind": "item", "key_field_ids": ["items.order_id"]}, "owner_ids": ["team"]}],
            "joins": [{"id": "items_orders", "from_dataset_id": "items", "to_dataset_id": "orders", "from_field_ids": ["items.order_id"], "to_field_ids": ["orders.order_id"], "cardinality": cardinality, "approved": approved}],
        }
    )


def intent_for_orders_grouping():
    return AnalyticalIntent.model_validate(
        {
            "query_id": "q-join",
            "tenant_id": "tenant-a",
            "dataset_id": "items",
            "semantic_contract": {"contract_id": "commerce", "contract_version": "v1"},
            "metrics": [{"metric_id": "item_gmv"}],
            "group_by": [{"dimension_id": "order_status"}],
        }
    )


def test_many_to_one_path_is_safe_for_item_grain_to_order_dimension():
    validate_join_safety(intent_for_orders_grouping(), contract_with_join())


@pytest.mark.parametrize(
    "cardinality, approved, expected",
    [
        ("many_to_many", True, "no approved many-to-one join path"),
        ("many_to_one", False, "no approved many-to-one join path"),
        ("one_to_many", True, "no approved many-to-one join path"),
    ],
)
def test_join_validation_rejects_unsafe_paths(cardinality, approved, expected):
    with pytest.raises(JoinValidationError, match=expected):
        validate_join_safety(
            intent_for_orders_grouping(), contract_with_join(cardinality, approved)
        )


def test_join_validation_rejects_multiple_metric_grains():
    contract = contract_with_join()
    data = deepcopy(contract.model_dump())
    data["metrics"].append(
        {
            "id": "order_count",
            "dataset_id": "orders",
            "aggregation": "count",
            "grain": {"kind": "entity", "key_field_ids": ["orders.order_id"]},
            "owner_ids": ["team"],
        }
    )
    contract = SemanticContract.model_validate(data)
    intent_data = intent_for_orders_grouping().model_dump()
    intent_data["metrics"].append({"metric_id": "order_count"})
    intent = AnalyticalIntent.model_validate(intent_data)

    with pytest.raises(JoinValidationError, match="multiple metric datasets"):
        validate_join_safety(intent, contract)
