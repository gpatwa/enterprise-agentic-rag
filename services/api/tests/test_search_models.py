from __future__ import annotations

import pytest
from pydantic import ValidationError


def _scope(**overrides):
    values = {
        "tenant_id": "tenant-acme",
        "principal_id": "user-1",
        "purpose": "support_resolution",
        "acl_tokens": ["tenant:tenant-acme", "group:support", "group:support"],
    }
    values.update(overrides)
    return values


def test_search_scope_normalizes_text_and_acl_tokens():
    from app.search.models import SearchScope

    scope = SearchScope(
        tenant_id=" tenant-acme ",
        principal_id=" user-1 ",
        purpose=" support_resolution ",
        acl_tokens=["group:support", "tenant:tenant-acme", "group:support"],
    )

    assert scope.tenant_id == "tenant-acme"
    assert scope.principal_id == "user-1"
    assert scope.acl_tokens == ("group:support", "tenant:tenant-acme")


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": ""},
        {"principal_id": ""},
        {"purpose": ""},
        {"acl_tokens": []},
        {"acl_tokens": ["group:support"]},
    ],
)
def test_search_scope_rejects_invalid_security_context(overrides):
    from app.search.models import SearchScope

    with pytest.raises(ValidationError):
        SearchScope(**_scope(**overrides))


def test_search_request_is_immutable_and_round_trips_json():
    from app.search.models import FilterOperator, SearchMode, SearchRequest

    request = SearchRequest(
        text="export timeout",
        scope=_scope(),
        mode=SearchMode.HYBRID,
        filters=[{"field": "status", "operator": FilterOperator.EQ, "value": "open"}],
        limit=5,
        request_id="request-1",
    )

    assert SearchRequest.model_validate_json(request.model_dump_json()) == request
    with pytest.raises(ValidationError):
        request.limit = 20


def test_search_request_rejects_unsafe_filter_field_and_bad_limits():
    from app.search.models import SearchRequest

    with pytest.raises(ValidationError):
        SearchRequest(text="query", scope=_scope(), filters=[{"field": "status;drop", "value": "open"}])
    with pytest.raises(ValidationError):
        SearchRequest(text="query", scope=_scope(), limit=0)


def test_bulk_write_result_requires_consistent_counts():
    from app.search.models import BulkWriteResult, SearchWriteError

    error = SearchWriteError(document_id="doc-1", code="mapping", message="bad field")
    with pytest.raises(ValidationError):
        BulkWriteResult(attempted=1, succeeded=1, failed=0, errors=[error])

    result = BulkWriteResult(attempted=1, succeeded=0, failed=1, errors=[error])
    assert result.failed == len(result.errors)
