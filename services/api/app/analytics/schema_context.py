# services/api/app/analytics/schema_context.py
"""
Semantic layer for the Olist Brazilian E-Commerce dataset.

Provides schema descriptions, column metadata, table relationships,
and common business metrics so the LLM generates correct SQL without
hallucinating column names or join paths.
"""
from typing import Dict, List

# ── Olist Schema ──────────────────────────────────────────────────────

OLIST_SCHEMA: Dict[str, dict] = {
    "olist_customers": {
        "description": "Customer profiles. One row per unique customer.",
        "row_count_approx": 99441,
        "columns": {
            "customer_id": {"type": "VARCHAR", "description": "FK used in orders table", "pk": False},
            "customer_unique_id": {"type": "VARCHAR", "description": "Unique customer identifier (deduplicated)", "pk": True},
            "customer_zip_code_prefix": {"type": "VARCHAR", "description": "First 5 digits of customer zip code"},
            "customer_city": {"type": "VARCHAR", "description": "Customer city name"},
            "customer_state": {"type": "VARCHAR(2)", "description": "Customer state code (e.g. SP, RJ, MG)"},
        },
        "keywords": ["customer", "city", "state", "location", "zip"],
    },
    "olist_orders": {
        "description": "Main orders table. One row per order. Links to customers, items, payments, reviews.",
        "row_count_approx": 99441,
        "columns": {
            "order_id": {"type": "VARCHAR", "description": "Unique order identifier", "pk": True},
            "customer_id": {"type": "VARCHAR", "description": "FK to olist_customers.customer_id"},
            "order_status": {"type": "VARCHAR", "description": "Order status: delivered, shipped, canceled, unavailable, invoiced, processing, created, approved"},
            "order_purchase_timestamp": {"type": "TIMESTAMP", "description": "When the order was placed by the customer"},
            "order_approved_at": {"type": "TIMESTAMP", "description": "When payment was approved"},
            "order_delivered_carrier_date": {"type": "TIMESTAMP", "description": "When order was handed to logistics carrier"},
            "order_delivered_customer_date": {"type": "TIMESTAMP", "description": "Actual delivery date to customer"},
            "order_estimated_delivery_date": {"type": "TIMESTAMP", "description": "Estimated delivery date shown to customer at purchase"},
        },
        "keywords": ["order", "purchase", "delivery", "status", "shipped", "canceled", "delivered"],
    },
    "olist_order_items": {
        "description": "Order line items. Multiple rows per order (one per product in the order).",
        "row_count_approx": 112650,
        "columns": {
            "order_id": {"type": "VARCHAR", "description": "FK to olist_orders.order_id"},
            "order_item_id": {"type": "INTEGER", "description": "Sequential item number within the order (1, 2, 3...)"},
            "product_id": {"type": "VARCHAR", "description": "FK to olist_products.product_id"},
            "seller_id": {"type": "VARCHAR", "description": "FK to olist_sellers.seller_id"},
            "shipping_limit_date": {"type": "TIMESTAMP", "description": "Seller shipping deadline"},
            "price": {"type": "NUMERIC", "description": "Item price in BRL (Brazilian Real)"},
            "freight_value": {"type": "NUMERIC", "description": "Shipping cost for this item in BRL"},
        },
        "keywords": ["item", "product", "price", "freight", "shipping", "seller", "cost"],
    },
    "olist_order_payments": {
        "description": "Payment information for orders. Multiple rows per order (one per payment method).",
        "row_count_approx": 103886,
        "columns": {
            "order_id": {"type": "VARCHAR", "description": "FK to olist_orders.order_id"},
            "payment_sequential": {"type": "INTEGER", "description": "Sequential payment number (1, 2, ...)"},
            "payment_type": {"type": "VARCHAR", "description": "Payment method: credit_card, boleto, voucher, debit_card"},
            "payment_installments": {"type": "INTEGER", "description": "Number of installments chosen by customer"},
            "payment_value": {"type": "NUMERIC", "description": "Payment amount in BRL. This is the revenue column."},
        },
        "keywords": ["payment", "revenue", "credit", "boleto", "installment", "value", "money", "amount"],
    },
    "olist_order_reviews": {
        "description": "Customer reviews after order delivery. One row per review.",
        "row_count_approx": 100000,
        "columns": {
            "review_id": {"type": "VARCHAR", "description": "Unique review identifier", "pk": True},
            "order_id": {"type": "VARCHAR", "description": "FK to olist_orders.order_id"},
            "review_score": {"type": "INTEGER", "description": "Rating from 1 (worst) to 5 (best)"},
            "review_comment_title": {"type": "TEXT", "description": "Review title (optional, often NULL)"},
            "review_comment_message": {"type": "TEXT", "description": "Review body text (optional)"},
            "review_creation_date": {"type": "TIMESTAMP", "description": "When review was submitted"},
            "review_answer_timestamp": {"type": "TIMESTAMP", "description": "When review answer was posted"},
        },
        "keywords": ["review", "rating", "score", "satisfaction", "feedback", "star"],
    },
    "olist_products": {
        "description": "Product catalog. One row per product.",
        "row_count_approx": 32951,
        "columns": {
            "product_id": {"type": "VARCHAR", "description": "Unique product identifier", "pk": True},
            "product_category_name": {"type": "VARCHAR", "description": "Product category in Portuguese (e.g. beleza_saude, informatica_acessorios)"},
            "product_name_lenght": {"type": "INTEGER", "description": "Character count of product name"},
            "product_description_lenght": {"type": "INTEGER", "description": "Character count of product description"},
            "product_photos_qty": {"type": "INTEGER", "description": "Number of product photos"},
            "product_weight_g": {"type": "INTEGER", "description": "Product weight in grams"},
            "product_length_cm": {"type": "INTEGER", "description": "Product length in cm"},
            "product_height_cm": {"type": "INTEGER", "description": "Product height in cm"},
            "product_width_cm": {"type": "INTEGER", "description": "Product width in cm"},
        },
        "keywords": ["product", "category", "weight", "dimension", "catalog"],
    },
    "olist_sellers": {
        "description": "Seller profiles. One row per seller.",
        "row_count_approx": 3095,
        "columns": {
            "seller_id": {"type": "VARCHAR", "description": "Unique seller identifier", "pk": True},
            "seller_zip_code_prefix": {"type": "VARCHAR", "description": "First 5 digits of seller zip code"},
            "seller_city": {"type": "VARCHAR", "description": "Seller city name"},
            "seller_state": {"type": "VARCHAR(2)", "description": "Seller state code"},
        },
        "keywords": ["seller", "vendor", "merchant", "supplier"],
    },
    "olist_geolocation": {
        "description": "Brazilian zip codes with lat/lng coordinates. Multiple rows per zip code (different points).",
        "row_count_approx": 1000163,
        "columns": {
            "geolocation_zip_code_prefix": {"type": "VARCHAR", "description": "First 5 digits of zip code"},
            "geolocation_lat": {"type": "NUMERIC", "description": "Latitude"},
            "geolocation_lng": {"type": "NUMERIC", "description": "Longitude"},
            "geolocation_city": {"type": "VARCHAR", "description": "City name"},
            "geolocation_state": {"type": "VARCHAR(2)", "description": "State code"},
        },
        "keywords": ["geo", "location", "latitude", "longitude", "map", "geography"],
    },
}

# ── Common Business Metrics ───────────────────────────────────────────

COMMON_METRICS = {
    "revenue": {
        "sql": "SUM(op.payment_value)",
        "tables": ["olist_order_payments op"],
        "join": "JOIN olist_order_payments op ON o.order_id = op.order_id",
        "description": "Total revenue in BRL from payment_value",
    },
    "total_orders": {
        "sql": "COUNT(DISTINCT o.order_id)",
        "tables": ["olist_orders o"],
        "join": "",
        "description": "Count of unique orders",
    },
    "average_order_value": {
        "sql": "AVG(op.payment_value)",
        "tables": ["olist_order_payments op"],
        "join": "JOIN olist_order_payments op ON o.order_id = op.order_id",
        "description": "Average payment value per order",
    },
    "average_review_score": {
        "sql": "AVG(r.review_score)",
        "tables": ["olist_order_reviews r"],
        "join": "JOIN olist_order_reviews r ON o.order_id = r.order_id",
        "description": "Average customer review rating (1-5 scale)",
    },
    "delivery_time_days": {
        "sql": "AVG(EXTRACT(EPOCH FROM (o.order_delivered_customer_date - o.order_purchase_timestamp)) / 86400)",
        "tables": ["olist_orders o"],
        "join": "",
        "description": "Average days from purchase to delivery",
    },
    "late_delivery_rate": {
        "sql": "AVG(CASE WHEN o.order_delivered_customer_date > o.order_estimated_delivery_date THEN 1.0 ELSE 0.0 END)",
        "tables": ["olist_orders o"],
        "join": "",
        "description": "Fraction of orders delivered after estimated date",
    },
}

# ── Table Relationships ───────────────────────────────────────────────

TABLE_RELATIONSHIPS = [
    {"from": "olist_orders.customer_id", "to": "olist_customers.customer_id", "type": "many-to-one"},
    {"from": "olist_order_items.order_id", "to": "olist_orders.order_id", "type": "many-to-one"},
    {"from": "olist_order_items.product_id", "to": "olist_products.product_id", "type": "many-to-one"},
    {"from": "olist_order_items.seller_id", "to": "olist_sellers.seller_id", "type": "many-to-one"},
    {"from": "olist_order_payments.order_id", "to": "olist_orders.order_id", "type": "many-to-one"},
    {"from": "olist_order_reviews.order_id", "to": "olist_orders.order_id", "type": "many-to-one"},
    {"from": "olist_customers.customer_zip_code_prefix", "to": "olist_geolocation.geolocation_zip_code_prefix", "type": "many-to-many"},
    {"from": "olist_sellers.seller_zip_code_prefix", "to": "olist_geolocation.geolocation_zip_code_prefix", "type": "many-to-many"},
]


# ── Public API ────────────────────────────────────────────────────────

def get_all_table_names() -> List[str]:
    """Return all valid Olist table names."""
    return list(OLIST_SCHEMA.keys())


def build_schema_prompt(query: str) -> str:
    """
    Build a schema context prompt for the LLM, selecting only tables
    relevant to the user's query via keyword matching.

    Returns a structured text block describing tables, columns, joins,
    and common metrics.
    """
    query_lower = query.lower()
    words = set(query_lower.split())

    # Score tables by keyword relevance
    scored_tables = []
    for table_name, table_info in OLIST_SCHEMA.items():
        score = 0
        for kw in table_info.get("keywords", []):
            if kw in query_lower:
                score += 2
        # Also check column descriptions
        for col_name, col_info in table_info["columns"].items():
            if col_name.replace("_", " ") in query_lower or any(w in col_info["description"].lower() for w in words if len(w) > 3):
                score += 1
        if score > 0:
            scored_tables.append((table_name, table_info, score))

    # If no tables matched, include the core tables (orders, payments, items)
    if not scored_tables:
        core = ["olist_orders", "olist_order_payments", "olist_order_items", "olist_customers"]
        scored_tables = [(t, OLIST_SCHEMA[t], 1) for t in core]

    # Sort by relevance and take top 5
    scored_tables.sort(key=lambda x: x[2], reverse=True)
    selected = scored_tables[:5]

    # Build prompt
    lines = ["## Database Schema (PostgreSQL)\n"]

    for table_name, table_info, _ in selected:
        lines.append(f"### {table_name}")
        lines.append(f"-- {table_info['description']} (~{table_info['row_count_approx']:,} rows)")
        lines.append("Columns:")
        for col_name, col_info in table_info["columns"].items():
            lines.append(f"  - {col_name} ({col_info['type']}): {col_info['description']}")
        lines.append("")

    # Add relevant relationships
    selected_names = {t[0] for t in selected}
    lines.append("### Relationships (JOIN paths)")
    for rel in TABLE_RELATIONSHIPS:
        from_table = rel["from"].split(".")[0]
        to_table = rel["to"].split(".")[0]
        if from_table in selected_names or to_table in selected_names:
            lines.append(f"  - {rel['from']} → {rel['to']} ({rel['type']})")
    lines.append("")

    # Add common metrics
    lines.append("### Common Business Metrics")
    for metric_name, metric_info in COMMON_METRICS.items():
        lines.append(f"  - {metric_name}: {metric_info['sql']} -- {metric_info['description']}")
    lines.append("")

    lines.append("### Important Notes")
    lines.append("- All monetary values are in BRL (Brazilian Real)")
    lines.append("- Use olist_orders.order_purchase_timestamp for time-based analysis")
    lines.append("- Revenue = SUM(olist_order_payments.payment_value)")
    lines.append("- Always JOIN through olist_orders.order_id as the central key")
    lines.append("- Product categories are in Portuguese (e.g. 'beleza_saude' = health & beauty)")

    return "\n".join(lines)
