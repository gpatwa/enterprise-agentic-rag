"""Narrow deterministic PostgreSQL compiler for certified analytical intents.

This adapter intentionally supports one physical dataset per query and excludes
joins and ratios. Policy filters are injected only from typed contract filters
and explicit context values; join and ratio gaps remain later milestones.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.semantic import (
    SemanticContract,
    SemanticDimension,
    SemanticField,
    SemanticFilter,
    SemanticMetric,
)


class CompilationError(ValueError):
    """Raised when a valid intent needs compiler behavior outside this spike."""


@dataclass(frozen=True)
class CompiledQuery:
    sql: str
    parameters: dict[str, Any]
    applied_filter_ids: tuple[str, ...] = ()
    dialect: str = "postgres"


class PostgreSQLCompiler:
    """Compile one validated semantic intent into parameterized PostgreSQL SQL."""

    dialect = "postgres"

    def compile(
        self,
        intent: AnalyticalIntent,
        contract: SemanticContract,
        policy_values: dict[str, Any] | None = None,
    ) -> CompiledQuery:
        intent.validate_against(contract)
        dataset = _find_by_id(contract.datasets, intent.dataset_id)
        selected_metrics = [_find_by_id(contract.metrics, metric.metric_id) for metric in intent.metrics]
        selected_dimensions = [_find_by_id(contract.dimensions, group.dimension_id) for group in intent.group_by]
        dimensions_by_id = {dimension.id: dimension for dimension in contract.dimensions}
        selected_fields = {field.id: field for field in contract.fields}

        if any(metric.dataset_id != dataset.id for metric in selected_metrics):
            raise CompilationError("this compiler supports metrics from the intent dataset only")
        if any(dimension.dataset_id != dataset.id for dimension in selected_dimensions):
            raise CompilationError("this compiler supports groupings from the intent dataset only")
        if any(metric.aggregation == "ratio" for metric in selected_metrics):
            raise CompilationError("ratio metrics are not supported by this compiler spike")
        dimensions = [
            _dimension_sql(group.time_granularity, dimension, selected_fields[dimension.field_id])
            for group, dimension in zip(intent.group_by, selected_dimensions, strict=True)
        ]
        metrics = [_metric_sql(metric, selected_fields) for metric in selected_metrics]
        select_items = [
            f"{expression} AS dimension_{index}" for index, expression in enumerate(dimensions)
        ] + [f"{expression} AS metric_{index}" for index, expression in enumerate(metrics)]

        required_filters = _required_filters(intent, contract)
        where_parts, parameters = _where_clause(
            intent,
            selected_fields,
            dimensions_by_id,
            dataset.id,
            required_filters,
            policy_values or {},
        )
        sql_parts = [
            f"SELECT {', '.join(select_items)}",
            f"FROM {_identifier(dataset.physical_name)} AS d0",
        ]
        if where_parts:
            sql_parts.append(f"WHERE {' AND '.join(where_parts)}")
        if dimensions:
            sql_parts.append(f"GROUP BY {', '.join(str(index + 1) for index in range(len(dimensions)))}")
        if intent.sort:
            order_parts = [
                f"{sort.target_kind}_{_sort_index(sort, intent)} {sort.direction.upper()}"
                for sort in intent.sort
            ]
            sql_parts.append(f"ORDER BY {', '.join(order_parts)}")
        sql_parts.append(f"LIMIT {intent.limit}")
        return CompiledQuery(
            sql="\n".join(sql_parts),
            parameters=parameters,
            applied_filter_ids=tuple(filter_.id for filter_ in required_filters),
            dialect=self.dialect,
        )


def _metric_sql(metric: SemanticMetric, fields: dict[str, SemanticField]) -> str:
    if metric.aggregation == "count":
        return "COUNT(*)"
    field = fields.get(metric.measure_field_id or "")
    if field is None:
        raise CompilationError(f"metric {metric.id} has no supported measure field")
    aggregate = {
        "sum": "SUM",
        "average": "AVG",
        "count_distinct": "COUNT(DISTINCT",
        "min": "MIN",
        "max": "MAX",
    }.get(metric.aggregation)
    if aggregate is None:
        raise CompilationError(f"metric aggregation {metric.aggregation} is not supported")
    column = _column(field)
    return f"{aggregate} {column})" if metric.aggregation == "count_distinct" else f"{aggregate}({column})"


def _dimension_sql(
    granularity: str | None, dimension: SemanticDimension, field: SemanticField
) -> str:
    column = _column(field)
    if granularity:
        if dimension.dimension_type != "temporal":
            raise CompilationError("time granularity requires a temporal dimension")
        return f"DATE_TRUNC('{granularity}', {column})"
    return column


def _where_clause(
    intent: AnalyticalIntent,
    fields: dict[str, SemanticField],
    dimensions: dict[str, SemanticDimension],
    dataset_id: str,
    required_filters: list[SemanticFilter],
    policy_values: dict[str, Any],
) -> tuple[list[str], dict[str, Any]]:
    clauses: list[str] = []
    parameters: dict[str, Any] = {}
    for filter_ in required_filters:
        field = fields.get(filter_.field_id)
        if field is None or field.dataset_id != dataset_id:
            raise CompilationError("required policy filter is outside the intent dataset")
        values = filter_.literal_value if filter_.value_source == "literal" else policy_values.get(filter_.id)
        if values is None:
            raise CompilationError(f"missing policy value for required filter {filter_.id}")
        if not isinstance(values, list):
            values = [values]
        clauses.extend(_filter_parts(field, filter_.operator, values, parameters))
    for filter_ in intent.filters:
        field = fields[filter_.field_id]
        if field.dataset_id != dataset_id:
            raise CompilationError("this compiler supports filters from the intent dataset only")
        clauses.extend(_filter_parts(field, filter_.operator, filter_.values, parameters))
    if intent.time_range:
        dimension = dimensions[intent.time_range.dimension_id]
        field = fields[dimension.field_id]
        if field.dataset_id != dataset_id:
            raise CompilationError("this compiler supports time ranges from the intent dataset only")
        parameter_index = len(parameters)
        if intent.time_range.start:
            key = f"p{parameter_index}"
            clauses.append(f"{_column(field)} >= :{key}")
            parameters[key] = intent.time_range.start
            parameter_index += 1
        if intent.time_range.end:
            key = f"p{parameter_index}"
            operator = "<=" if intent.time_range.inclusive_end else "<"
            clauses.append(f"{_column(field)} {operator} :{key}")
            parameters[key] = intent.time_range.end
    return clauses, parameters


def _filter_parts(
    field: SemanticField, operator_name: str, values: list[Any], parameters: dict[str, Any]
) -> list[str]:
    operator = {
        "equals": "=",
        "not_equals": "!=",
        "greater_than": ">",
        "greater_than_or_equal": ">=",
        "less_than": "<",
        "less_than_or_equal": "<=",
    }.get(operator_name)
    column = _column(field)
    if operator:
        key = f"p{len(parameters)}"
        parameters[key] = values[0]
        return [f"{column} {operator} :{key}"]
    keyword = "IN" if operator_name == "in" else "NOT IN"
    placeholders = []
    for value in values:
        key = f"p{len(parameters)}"
        parameters[key] = value
        placeholders.append(f":{key}")
    return [f"{column} {keyword} ({', '.join(placeholders)})"]


def _required_filters(intent: AnalyticalIntent, contract: SemanticContract) -> list[SemanticFilter]:
    selected_ids = {intent.dataset_id}
    selected_ids.update(metric.metric_id for metric in intent.metrics)
    selected_ids.update(group.dimension_id for group in intent.group_by)
    selected_ids.update(filter_.field_id for filter_ in intent.filters)
    selected_metric_ids = {selected.metric_id for selected in intent.metrics}
    required_ids = {
        filter_id
        for metric in contract.metrics
        if metric.id in selected_metric_ids
        for filter_id in metric.required_filter_ids
    }
    required_ids.update(
        filter_id
        for policy in contract.policies
        if set(policy.target_ids) & selected_ids
        for filter_id in policy.required_filter_ids
    )
    filters_by_id = {filter_.id: filter_ for filter_ in contract.filters}
    return [filters_by_id[filter_id] for filter_id in sorted(required_ids)]


def _sort_index(sort: Any, intent: AnalyticalIntent) -> int:
    targets = intent.metrics if sort.target_kind == "metric" else intent.group_by
    target_ids = [item.metric_id if sort.target_kind == "metric" else item.dimension_id for item in targets]
    return target_ids.index(sort.target_id)


def _column(field: SemanticField) -> str:
    return f"d0.{_identifier(field.physical_name)}"


def _identifier(value: str) -> str:
    escaped = value.replace('"', '""')
    return f'"{escaped}"'


def _find_by_id(values: list[Any], identifier: str) -> Any:
    return next(value for value in values if value.id == identifier)
