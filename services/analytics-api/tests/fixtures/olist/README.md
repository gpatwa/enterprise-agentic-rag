# Canonical Olist Metric Fixture

This deliberately small dataset is the SQL-independent source of truth for
analytics metric tests. It uses Olist-compatible column names and has six
orders, two customers, three categories, a canceled order, late deliveries, a
multi-item order, and split payments.

## Metric assumptions

- All listed outcome metrics are **delivered-only**. Canceled order `o-4` is
  excluded from revenue, order count, AOV, GMV, reviews, delivery duration,
  and late-rate calculations.
- **Order revenue** is the sum of payment rows after first aggregating them to
  one value per order. It is not attributable to individual product categories
  without an explicit allocation policy.
- **Item GMV** is the sum of `order_items.price`; category GMV groups that
  item-level value by `products.product_category_name`.
- Delivery duration is calendar-time days from purchase to actual delivery.
  A delivery is late only when actual delivery is later than the estimate.

`o-1` has two items and payments totaling BRL 100.00. A direct join between
payments and items incorrectly counts BRL 200.00 for that order; the expected
fixture preserves the BRL 470.00 erroneous joined total as a regression signal.

`expected_metrics.json` contains reviewable canonical results. The tests also
recalculate these values directly from the source rows so no SQL implementation
or semantic-layer definition can become its own oracle.

## Unresolved Semantic Questions

- Should reported revenue include freight, refunds, or only captured payments?
- Should average review score include every review on a delivered order when an
  order has multiple review rows, or use a designated primary review?
- Which timezone and timestamp rounding rule should govern delivery-duration
  and late-delivery reporting in a customer deployment?
