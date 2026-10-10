"""SQL-independent correctness checks for the canonical Olist fixture."""
from __future__ import annotations

import json
from collections import defaultdict
from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "olist"


def load_fixture() -> dict[str, list[dict] | dict]:
    """Load source rows and expected values without consulting production code."""
    names = ("customers", "orders", "order_items", "payments", "products", "reviews")
    data = {
        name: json.loads((FIXTURE_DIR / f"{name}.json").read_text())
        for name in names
    }
    data["expected"] = json.loads((FIXTURE_DIR / "expected_metrics.json").read_text())
    return data


def calculate_metrics(data: dict[str, list[dict] | dict]) -> dict[str, Decimal | int | dict[str, Decimal]]:
    """Calculate metric contracts at their intended order or item grain."""
    delivered_orders = {
        order["order_id"]: order
        for order in data["orders"]
        if order["order_status"] == "delivered"
    }
    payments_by_order: dict[str, Decimal] = defaultdict(Decimal)
    for payment in data["payments"]:
        if payment["order_id"] in delivered_orders:
            payments_by_order[payment["order_id"]] += Decimal(payment["payment_value"])

    product_categories = {
        product["product_id"]: product["product_category_name"]
        for product in data["products"]
    }
    category_gmv: dict[str, Decimal] = defaultdict(Decimal)
    item_gmv = Decimal()
    for item in data["order_items"]:
        if item["order_id"] in delivered_orders:
            price = Decimal(item["price"])
            item_gmv += price
            category_gmv[product_categories[item["product_id"]]] += price

    delivered_reviews = [
        review for review in data["reviews"] if review["order_id"] in delivered_orders
    ]
    delivery_days = []
    late_orders = 0
    for order in delivered_orders.values():
        purchased = datetime.fromisoformat(order["order_purchase_timestamp"])
        delivered = datetime.fromisoformat(order["order_delivered_customer_date"])
        estimated = datetime.fromisoformat(order["order_estimated_delivery_date"])
        delivery_days.append(Decimal((delivered - purchased).days))
        late_orders += delivered > estimated

    order_count = len(delivered_orders)
    revenue = sum(payments_by_order.values(), Decimal())
    return {
        "delivered_revenue_brl": revenue,
        "delivered_order_count": order_count,
        "average_order_value_brl": revenue / order_count,
        "delivered_item_gmv_brl": item_gmv,
        "category_item_gmv_brl": dict(category_gmv),
        "average_review_score": sum(
            (Decimal(review["review_score"]) for review in delivered_reviews), Decimal()
        ) / len(delivered_reviews),
        "average_delivery_duration_days": sum(delivery_days, Decimal()) / order_count,
        "late_delivery_rate": Decimal(late_orders) / order_count,
    }


def direct_payment_item_join_total(data: dict[str, list[dict] | dict]) -> Decimal:
    """Model the erroneous raw payments-to-items join without pre-aggregation."""
    delivered_ids = {
        order["order_id"] for order in data["orders"] if order["order_status"] == "delivered"
    }
    return sum(
        (
            Decimal(payment["payment_value"])
            for payment in data["payments"]
            for item in data["order_items"]
            if payment["order_id"] == item["order_id"] in delivered_ids
        ),
        Decimal(),
    )


def expected_decimal(expected: dict, name: str) -> Decimal:
    return Decimal(expected[name])


def test_canonical_fixture_has_required_order_and_customer_coverage():
    data = load_fixture()

    assert len(data["orders"]) >= 6
    assert {order["order_status"] for order in data["orders"]} >= {"delivered", "canceled"}
    assert len(data["customers"]) >= 2
    assert any(order["order_id"] == "o-1" for order in data["orders"])
    assert sum(item["order_id"] == "o-1" for item in data["order_items"]) == 2
    assert sum(payment["order_id"] == "o-1" for payment in data["payments"]) == 2


def test_canonical_metrics_match_reviewable_expected_values():
    data = load_fixture()
    metrics = calculate_metrics(data)
    expected = data["expected"]

    assert metrics["delivered_revenue_brl"] == expected_decimal(expected, "delivered_revenue_brl")
    assert metrics["delivered_order_count"] == expected["delivered_order_count"]
    assert metrics["average_order_value_brl"] == expected_decimal(expected, "average_order_value_brl")
    assert metrics["delivered_item_gmv_brl"] == expected_decimal(expected, "delivered_item_gmv_brl")
    assert metrics["category_item_gmv_brl"] == {
        category: Decimal(value) for category, value in expected["category_item_gmv_brl"].items()
    }
    assert metrics["average_review_score"] == expected_decimal(expected, "average_review_score")
    assert metrics["average_delivery_duration_days"] == expected_decimal(expected, "average_delivery_duration_days")
    assert metrics["late_delivery_rate"] == expected_decimal(expected, "late_delivery_rate")


def test_split_payments_are_aggregated_per_order_before_aov():
    data = load_fixture()
    metrics = calculate_metrics(data)

    naive_payment_row_average = Decimal("370.00") / 7
    assert metrics["average_order_value_brl"] == Decimal("74.00")
    assert metrics["average_order_value_brl"] != naive_payment_row_average


def test_direct_payment_to_item_join_exposes_fanout_overcount():
    data = load_fixture()
    expected = data["expected"]

    erroneous_total = direct_payment_item_join_total(data)
    assert erroneous_total == expected_decimal(expected, "direct_payment_item_join_revenue_brl")
    assert erroneous_total > calculate_metrics(data)["delivered_revenue_brl"]


def test_metric_results_are_stable_when_source_rows_are_reordered():
    data = load_fixture()
    reordered = deepcopy(data)
    for name in ("customers", "orders", "order_items", "payments", "products", "reviews"):
        reordered[name].reverse()

    assert calculate_metrics(reordered) == calculate_metrics(data)
    assert direct_payment_item_join_total(reordered) == direct_payment_item_join_total(data)
