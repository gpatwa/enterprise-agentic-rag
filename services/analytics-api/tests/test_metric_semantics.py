"""Regression checks for semantic definitions guarded by the canonical fixture."""
from app.analytics.schema_context import COMMON_METRICS
from app.service import _demo_result


def test_revenue_and_aov_aggregate_payment_rows_to_order_grain():
    assert "SUM(payment_value) AS order_revenue" in COMMON_METRICS["revenue"]["join"]
    assert "payment_totals.order_revenue" in COMMON_METRICS["revenue"]["sql"]
    assert "payment_totals.order_revenue" in COMMON_METRICS["average_order_value"]["sql"]
    assert "o.order_status = 'delivered'" in COMMON_METRICS["revenue"]["sql"]


def test_category_analysis_uses_item_gmv_not_payment_revenue():
    demo = _demo_result("Category performance")

    assert demo["columns"] == ["product_category", "item_gmv"]
    assert "SUM(oi.price) AS item_gmv" in demo["sql"]
    assert "olist_order_payments" not in demo["sql"]


def test_delivery_metrics_are_explicitly_delivered_order_metrics():
    assert "delivered" in COMMON_METRICS["revenue"]["description"].lower()
    assert "delivered" in COMMON_METRICS["average_order_value"]["description"].lower()
    assert "o.order_status = 'delivered'" in COMMON_METRICS["delivery_time_days"]["sql"]
    assert "o.order_status = 'delivered'" in COMMON_METRICS["late_delivery_rate"]["sql"]
