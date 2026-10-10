import asyncio

import pytest

from app.search.errors import OpenSearchError
from app.search.models import SearchMode, SearchRequest, SearchResponse, SearchScope
from app.search.service import SearchService


def _request() -> SearchRequest:
    return SearchRequest(
        text="export",
        scope=SearchScope(
            tenant_id="tenant-acme",
            principal_id="agent-1",
            purpose="support-search",
            acl_tokens=("tenant:tenant-acme", "group:support"),
        ),
        mode=SearchMode.LEXICAL,
    )


def _response() -> SearchResponse:
    return SearchResponse(index_alias="support-search", index_generation="generation-1")


@pytest.mark.asyncio
async def test_search_service_bounds_provider_and_emits_success():
    events = []

    class Provider:
        async def search(self, request):
            return _response()

    service = SearchService(Provider(), timeout_seconds=0.1, event_sink=lambda name, attrs: events.append((name, attrs)))
    assert await service.search(_request()) == _response()
    assert events[-1][0] == "search.success"


@pytest.mark.asyncio
async def test_search_service_falls_back_only_for_retryable_failures():
    class Provider:
        async def search(self, request):
            raise ConnectionError("connection refused")

    service = SearchService(Provider(), timeout_seconds=0.1, fallback=lambda request: asyncio.sleep(0, result=_response()))
    assert await service.search(_request()) == _response()

    class AuthProvider:
        async def search(self, request):
            raise OpenSearchError(code="auth", message="denied", retryable=False, operation="search")

    blocked = SearchService(AuthProvider(), timeout_seconds=0.1, fallback=lambda request: asyncio.sleep(0, result=_response()))
    with pytest.raises(OpenSearchError, match="denied"):
        await blocked.search(_request())


@pytest.mark.asyncio
async def test_search_service_preserves_cancellation():
    class SlowProvider:
        async def search(self, request):
            await asyncio.sleep(10)

    task = asyncio.create_task(SearchService(SlowProvider(), timeout_seconds=10).search(_request()))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_support_indexer_maps_enterprise_results(monkeypatch):
    import app.support.indexer as indexer
    from app.search.models import RetrievalSource, SearchResult

    class Embedder:
        async def embed_query(self, query):
            return [0.1, 0.2]

    class Enterprise:
        async def search(self, request):
            assert request.mode == SearchMode.HYBRID
            assert request.scope.tenant_id == "tenant-acme"
            return SearchResponse(
                results=(
                    SearchResult(
                        document_id="ticket-1",
                        tenant_id="tenant-acme",
                        source_type="ticket",
                        source_id="A-1",
                        title="Export timeout",
                        text="Restart the worker",
                        metadata={"provider": "zendesk", "status": "open", "tags": ["export"]},
                        score=0.03,
                        rank=1,
                        retrieval_source=RetrievalSource.HYBRID,
                        lexical_score=8.0,
                        vector_score=0.9,
                        fusion_score=0.03,
                        index_generation="generation-1",
                        content_version="v1",
                        permission_version="acl-v1",
                    ),
                ),
                index_alias="support-search",
                index_generation="generation-1",
            )

    monkeypatch.setattr(indexer, "_embed_client", Embedder())
    indexer.set_enterprise_search_service(Enterprise())
    try:
        results = await indexer.SupportIndexer().search(tenant_id="tenant-acme", query="export")
    finally:
        indexer.set_enterprise_search_service(None)

    assert results[0]["id"] == "ticket-1"
    assert results[0]["retrieval_source"] == "hybrid"
    assert results[0]["tags"] == ["export"]
