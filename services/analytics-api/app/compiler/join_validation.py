"""Fail-closed join-path and aggregation-grain checks for analytical intents."""
from __future__ import annotations

from collections import deque

from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import SemanticContract, SemanticJoin


class JoinValidationError(ValueError):
    """Raised when an intent would require an unsafe or ambiguous join path."""


def validate_join_safety(intent: AnalyticalIntent, contract: SemanticContract) -> None:
    """Validate that all referenced datasets connect without fanout.

    The allowed traversal is from a many-side fact dataset to a one-side
    dimension dataset. Reverse one-to-many traversal, many-to-many joins, and
    unapproved paths are rejected until a later compiler can prove their grain.
    """
    intent.validate_against(contract)
    metric_datasets = {
        metric.dataset_id
        for metric in contract.metrics
        if metric.id in {selected.metric_id for selected in intent.metrics}
    }
    if len(metric_datasets) > 1:
        raise JoinValidationError("multiple metric datasets have ambiguous aggregation grain")

    referenced = {intent.dataset_id}
    referenced.update(
        dimension.dataset_id
        for dimension in contract.dimensions
        if dimension.id in {group.dimension_id for group in intent.group_by}
    )
    referenced.update(
        field.dataset_id
        for field in contract.fields
        if field.id in {filter_.field_id for filter_ in intent.filters}
    )
    if intent.time_range:
        referenced.add(
            next(
                dimension.dataset_id
                for dimension in contract.dimensions
                if dimension.id == intent.time_range.dimension_id
            )
        )
    if len(referenced) <= 1:
        return

    safe_reachable = _safe_reachable_datasets(intent.dataset_id, contract.joins)
    missing = sorted(referenced - safe_reachable)
    if missing:
        raise JoinValidationError(
            f"no approved many-to-one join path from {intent.dataset_id} to: {', '.join(missing)}"
        )


def _safe_reachable_datasets(start: str, joins: list[SemanticJoin]) -> set[str]:
    adjacency: dict[str, set[str]] = {}
    for join in joins:
        if not join.approved:
            continue
        if join.cardinality == "many_to_many":
            continue
        adjacency.setdefault(join.from_dataset_id, set())
        adjacency.setdefault(join.to_dataset_id, set())
        if join.cardinality in {"one_to_one", "many_to_one"}:
            adjacency[join.from_dataset_id].add(join.to_dataset_id)
        if join.cardinality == "one_to_one":
            adjacency[join.to_dataset_id].add(join.from_dataset_id)

    reachable = {start}
    pending = deque([start])
    while pending:
        current = pending.popleft()
        for neighbor in adjacency.get(current, set()):
            if neighbor not in reachable:
                reachable.add(neighbor)
                pending.append(neighbor)
    return reachable
