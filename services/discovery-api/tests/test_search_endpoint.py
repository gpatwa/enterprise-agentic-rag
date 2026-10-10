"""Focused contract tests for the typed local search endpoint."""
import json
from datetime import datetime, timezone
from pathlib import Path

from app.domain.models import ExperienceRecord, UserProfile
from app.routes.search import LocalSearchService, SearchRequest, search
from app.search.mapper import CatalogDocumentInput, map_catalog_document
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden"


def _request(**overrides):
    values = {
        "tenant_id": "tenant-orbit",
        "principal_id": "user-001",
        "request_id": "request-search-001",
        "purpose": "search",
        "locale": "en-US",
        "device": "web",
        "age": 16,
    }
    query = overrides.pop("query", "mystery")
    page = overrides.pop("page", 1)
    page_size = overrides.pop("page_size", 20)
    values.update(overrides)
    return SearchRequest(
        query=query,
        context=DiscoveryRequestContext(**values),
        page=page,
        page_size=page_size,
    )


def _user():
    return UserProfile(
        user_id="user-001", tenant_id="tenant-orbit", persona="short-history", locale="en-US",
        age_rating_limit="T", devices=("desktop",), history_length="short",
        preferences={"genres": (), "themes": ()}, consent_state="personalization_allowed", synthetic=True,
    )


def _documents():
    records = [ExperienceRecord.model_validate(item) for item in json.loads((FIXTURE / "experiences.json").read_text())[:2]]
    return tuple(
        map_catalog_document(CatalogDocumentInput(
            record=record, tenant_id=record.tenant_id, source_type="fixture", source_id=record.experience_id,
            provenance_ref=f"fixture://{record.experience_id}", content_version="v1", permission_version="v1",
            embedding=tuple(0.01 for _ in range(384)),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc), updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )) for record in records
    )


def test_search_returns_bounded_results_and_lineage_token():
    response = LocalSearchService(_documents(), (_user(),)).search(_request())

    assert response.error is None
    assert response.results[0].experience_id == "exp-001"
    assert response.impression_token is not None
    response.impression_token.validate_for(_request().context)
    assert response.decision_trace is not None
    assert all("user_id" not in item.model_dump() for item in response.results)


def test_search_is_deterministic_for_same_catalog_and_request_shape():
    service = LocalSearchService(_documents(), (_user(),))
    first = service.search(_request(request_id="request-a"))
    second = service.search(_request(request_id="request-b"))

    assert tuple(item.experience_id for item in first.results) == tuple(item.experience_id for item in second.results)
    assert first.query == second.query


def test_invalid_profile_context_fails_closed_without_token():
    response = LocalSearchService(_documents(), ()).search(_request())

    assert response.error is not None
    assert response.error.code == "missing_context"
    assert response.results == ()
    assert response.impression_token is None


def test_tenant_scope_is_rejected_and_private_query_is_not_echoed_on_error():
    context = DiscoveryRequestContext(
        tenant_id="tenant-other", principal_id="user-001", request_id="request-tenant",
        purpose="search", locale="en-US", device="web", age=16,
    )
    response = LocalSearchService(_documents(), (_user(),)).search(SearchRequest(query='private phrase "secret"', context=context))

    assert response.error is not None
    assert response.error.code == "missing_context"
    assert response.query is None
    assert "secret" not in response.model_dump_json()


def test_fastapi_handler_uses_the_configured_provider(monkeypatch):
    monkeypatch.setattr("app.routes.search.service", LocalSearchService(_documents(), (_user(),)))
    response = search(_request(page_size=1))

    assert len(response.results) == 1
    assert response.request_id == "request-search-001"
