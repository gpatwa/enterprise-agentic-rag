from __future__ import annotations

from datetime import datetime

import pytest


def _scope():
    from app.search.models import SearchScope

    return SearchScope(
        tenant_id="tenant-a",
        principal_id="agent-1",
        purpose="support-search",
        acl_tokens=("tenant:tenant-a", "group:support"),
    )


def test_compiler_always_injects_tenant_and_acl_predicates():
    from app.search.filters import compile_filters
    from app.search.models import FilterOperator, SearchFilter

    query = compile_filters(
        _scope(),
        [SearchFilter(field="status", operator=FilterOperator.EQ, value="open")],
    )
    assert query == {
        "bool": {
            "filter": [
                {"term": {"tenant_id": "tenant-a"}},
                {"terms": {"acl_tokens": ["group:support", "tenant:tenant-a"]}},
                {"term": {"status": "open"}},
            ]
        }
    }


def test_filters_are_allowlisted_and_never_accept_policy_fields():
    from app.search.filters import ProtectedSearchFieldError, SearchFilterCompilerError, compile_filters
    from app.search.models import SearchFilter

    with pytest.raises(ProtectedSearchFieldError):
        compile_filters(_scope(), [SearchFilter(field="tenant_id", value="tenant-b")])
    with pytest.raises(ProtectedSearchFieldError):
        compile_filters(_scope(), [SearchFilter(field="acl_tokens", value="tenant-b")])
    with pytest.raises(SearchFilterCompilerError, match="unsupported"):
        compile_filters(_scope(), [SearchFilter(field="metadata.owner", value="alice")])


def test_compiler_handles_ranges_prefixes_and_negative_predicates():
    from app.search.filters import compile_filters
    from app.search.models import FilterOperator, SearchFilter

    query = compile_filters(
        _scope(),
        [
            SearchFilter(field="source_id", operator=FilterOperator.PREFIX, value="42"),
            SearchFilter(field="updated_at", operator=FilterOperator.GTE, value=datetime(2026, 8, 1)),
            SearchFilter(field="status", operator=FilterOperator.NOT_IN, value=["closed", "spam"]),
        ],
    )
    assert {"prefix": {"source_id": "42"}} in query["bool"]["filter"]
    assert {"range": {"updated_at": {"gte": "2026-08-01T00:00:00"}}} in query["bool"]["filter"]
    assert query["bool"]["must_not"] == [{"terms": {"status": ["closed", "spam"]}}]


@pytest.mark.parametrize(
    "field,operator,value",
    [
        ("status", "in", "open"),
        ("status", "in", []),
        ("status", "in", list(range(101))),
        ("source_id", "prefix", {"starts_with": "x"}),
        ("updated_at", "gt", "not-a-date"),
    ],
)
def test_malformed_or_unbounded_values_fail_closed(field, operator, value):
    from app.search.filters import SearchFilterCompilerError, compile_filters
    from app.search.models import SearchFilter

    with pytest.raises(SearchFilterCompilerError):
        compile_filters(_scope(), [SearchFilter(field=field, operator=operator, value=value)])


def test_request_compiler_uses_the_request_scope_not_user_filter_values():
    from app.search.filters import compile_request_filters
    from app.search.models import SearchRequest

    request = SearchRequest(
        text="export timeout",
        scope=_scope(),
        filters=({"field": "provider", "operator": "eq", "value": "zendesk"},),
    )
    query = compile_request_filters(request)
    assert {"term": {"tenant_id": "tenant-a"}} in query["bool"]["filter"]
    assert {"term": {"provider": "zendesk"}} in query["bool"]["filter"]
