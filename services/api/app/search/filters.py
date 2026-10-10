from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from typing import Any

from app.search.models import FilterOperator, SearchFilter, SearchRequest, SearchScope


class SearchFilterCompilerError(ValueError):
    """A request cannot be safely represented as a scoped backend filter."""


class ProtectedSearchFieldError(SearchFilterCompilerError):
    """A caller attempted to control a field owned by authorization policy."""


_PROTECTED_FIELDS = frozenset({"tenant_id", "acl_tokens"})
_FIELD_RULES: Mapping[str, frozenset[FilterOperator]] = {
    "document_id": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN, FilterOperator.PREFIX}
    ),
    "source_type": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "source_id": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN, FilterOperator.PREFIX}
    ),
    "provider": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "title.keyword": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN, FilterOperator.PREFIX}
    ),
    "status": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "priority": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "category": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "channel": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "locale": frozenset(
        {FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}
    ),
    "tags": frozenset({FilterOperator.EQ, FilterOperator.NE, FilterOperator.IN, FilterOperator.NOT_IN}),
    "created_at": frozenset(
        {
            FilterOperator.EQ,
            FilterOperator.NE,
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
        }
    ),
    "updated_at": frozenset(
        {
            FilterOperator.EQ,
            FilterOperator.NE,
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
        }
    ),
}

_MAX_TERMS = 100
_MAX_VALUE_LENGTH = 512


def compile_filters(
    scope: SearchScope,
    filters: Sequence[SearchFilter] = (),
) -> dict[str, Any]:
    """Compile an authorization-scoped, allowlisted OpenSearch bool query.

    The tenant and ACL clauses are always generated from ``scope`` and cannot be
    overridden by user filters. User predicates are ANDed with those clauses.
    """
    _validate_scope(scope)
    query: dict[str, Any] = {
        "bool": {
            "filter": [
                {"term": {"tenant_id": scope.tenant_id}},
                {"terms": {"acl_tokens": list(scope.acl_tokens)}},
            ],
            "must_not": [],
        }
    }
    for raw_filter in filters:
        search_filter = _coerce_filter(raw_filter)
        clause = _compile_user_filter(search_filter)
        if search_filter.operator in {FilterOperator.NE, FilterOperator.NOT_IN}:
            query["bool"]["must_not"].append(clause)
        else:
            query["bool"]["filter"].append(clause)
    if not query["bool"]["must_not"]:
        query["bool"].pop("must_not")
    return query


def compile_request_filters(request: SearchRequest) -> dict[str, Any]:
    """Compile the filter portion of a complete backend-neutral request."""
    return compile_filters(request.scope, request.filters)


def _validate_scope(scope: SearchScope) -> None:
    if not isinstance(scope, SearchScope):
        raise SearchFilterCompilerError("search scope is required")
    required_token = f"tenant:{scope.tenant_id}"
    if required_token not in scope.acl_tokens:
        raise SearchFilterCompilerError("search scope is missing its tenant ACL token")


def _coerce_filter(value: SearchFilter) -> SearchFilter:
    if isinstance(value, SearchFilter):
        return value
    if isinstance(value, dict):
        try:
            return SearchFilter.model_validate(value)
        except Exception as error:
            raise SearchFilterCompilerError("invalid search filter") from error
    raise SearchFilterCompilerError("filters must contain SearchFilter values")


def _compile_user_filter(search_filter: SearchFilter) -> dict[str, Any]:
    field = search_filter.field.strip()
    operator = search_filter.operator
    if field in _PROTECTED_FIELDS:
        raise ProtectedSearchFieldError(f"filter field is policy-controlled: {field}")
    allowed_operators = _FIELD_RULES.get(field)
    if allowed_operators is None:
        raise SearchFilterCompilerError(f"unsupported search filter field: {field}")
    if operator not in allowed_operators:
        raise SearchFilterCompilerError(
            f"operator {operator.value!r} is not supported for filter field {field!r}"
        )

    if operator in {FilterOperator.IN, FilterOperator.NOT_IN}:
        values = _bounded_values(search_filter.value, field)
        return {"terms": {field: values}}
    if operator == FilterOperator.PREFIX:
        value = _bounded_field_value(search_filter.value, field)
        if not isinstance(value, str):
            raise SearchFilterCompilerError(f"prefix filter value must be text for {field!r}")
        return {"prefix": {field: value}}
    if operator in {
        FilterOperator.GT,
        FilterOperator.GTE,
        FilterOperator.LT,
        FilterOperator.LTE,
    }:
        value = _bounded_field_value(search_filter.value, field)
        return {"range": {field: {_RANGE_OPERATORS[operator]: _serialize_value(value)}}}
    return {"term": {field: _serialize_value(_bounded_field_value(search_filter.value, field))}}


_RANGE_OPERATORS = {
    FilterOperator.GT: "gt",
    FilterOperator.GTE: "gte",
    FilterOperator.LT: "lt",
    FilterOperator.LTE: "lte",
}


def _bounded_values(value: Any, field: str) -> list[Any]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        raise SearchFilterCompilerError("in/not_in filter values must be a sequence")
    values = list(value)
    if not values or len(values) > _MAX_TERMS:
        raise SearchFilterCompilerError(f"filter value list must contain 1-{_MAX_TERMS} values")
    return [_serialize_value(_bounded_field_value(item, field)) for item in values]


def _bounded_scalar(value: Any, field: str) -> Any:
    if value is None or isinstance(value, (dict, list, tuple, set, frozenset)):
        raise SearchFilterCompilerError(f"filter value must be a scalar for {field!r}")
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized or len(normalized) > _MAX_VALUE_LENGTH:
            raise SearchFilterCompilerError(f"filter text value is blank or too long for {field!r}")
        return normalized
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and (value != value or value in {float("inf"), float("-inf")}):
            raise SearchFilterCompilerError(f"filter number is not finite for {field!r}")
        return value
    if isinstance(value, (datetime, date)):
        return value
    raise SearchFilterCompilerError(f"unsupported filter value type for {field!r}")


def _bounded_field_value(value: Any, field: str) -> Any:
    bounded = _bounded_scalar(value, field)
    if field not in {"created_at", "updated_at"}:
        return bounded
    if isinstance(bounded, (datetime, date)):
        return bounded
    if isinstance(bounded, str):
        try:
            return datetime.fromisoformat(bounded.replace("Z", "+00:00"))
        except ValueError as error:
            raise SearchFilterCompilerError(f"invalid date value for {field!r}") from error
    raise SearchFilterCompilerError(f"date filter value must be a date for {field!r}")


def _serialize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


compile_search_filters = compile_filters
