from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.search.opensearch import OpenSearchProvider


def _config(**overrides):
    values = {
        "OPENSEARCH_INDEX_ALIAS": "support-search",
        "OPENSEARCH_MAX_RETRIES": 1,
        "OPENSEARCH_RETRY_ON_TIMEOUT": True,
        "OPENSEARCH_REQUEST_TIMEOUT_SECONDS": 5.0,
        "get_opensearch_url": lambda: "https://search.internal:9200",
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _scope():
    from app.search.models import SearchScope

    return SearchScope(
        tenant_id="tenant-acme",
        principal_id="agent-1",
        purpose="support-search",
        acl_tokens=("tenant:tenant-acme", "group:support"),
    )


class FakeSearchClient:
    def __init__(self, response):
        self.response = response
        self.search_calls: list[dict] = []

    async def info(self):
        return {"version": {"number": "2.15.0"}}

    async def search(self, *, index, body):
        self.search_calls.append({"index": index, "body": body})
        return self.response


class SequenceSearchClient(FakeSearchClient):
    def __init__(self, responses):
        super().__init__({})
        self.responses = list(responses)

    async def search(self, *, index, body):
        self.search_calls.append({"index": index, "body": body})
        return self.responses.pop(0)


def _hit(
    document_id="acme-ticket-1001",
    *,
    tenant_id="tenant-acme",
    acl_tokens=("tenant:tenant-acme", "group:support"),
    score=8.25,
):
    return {
        "_index": "support-search-20260823",
        "_id": document_id,
        "_score": score,
        "_source": {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "acl_tokens": list(acl_tokens),
            "source_type": "ticket",
            "source_id": "A-1001",
            "provider": "zendesk",
            "title": "Export timeout",
            "text": "Restart the export worker.",
            "metadata": {"status": "open"},
            "source_uri": "https://support.example.test/tickets/A-1001",
            "content_version": "sha256:version-1",
            "permission_version": "acl-v1",
            "embedding_model_version": None,
        },
        "highlight": {
            "title": ["<em>Export</em> timeout"],
            "text": ["Restart the <em>export</em> worker."],
        },
    }


@pytest.mark.asyncio
async def test_bm25_query_has_exact_id_phrase_boost_and_scoped_filters():
    from app.search.models import FilterOperator, SearchFilter, SearchMode, SearchRequest

    client = FakeSearchClient({"hits": {"total": {"value": 1, "relation": "eq"}, "hits": [_hit()]}})
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    response = await provider.search(
        SearchRequest(
            text="A-1001",
            scope=_scope(),
            mode=SearchMode.LEXICAL,
            filters=(
                SearchFilter(field="status", operator=FilterOperator.EQ, value="open"),
                SearchFilter(field="source_type", operator=FilterOperator.EQ, value="ticket"),
            ),
        )
    )

    assert len(response.results) == 1
    assert response.results[0].document_id == "acme-ticket-1001"
    assert response.results[0].retrieval_source.value == "lexical"
    assert response.results[0].lexical_score == 8.25
    assert response.results[0].highlights == (
        "<em>Export</em> timeout",
        "Restart the <em>export</em> worker.",
    )
    assert response.results[0].explanation.components == {"bm25": 8.25}

    body = client.search_calls[0]["body"]
    assert client.search_calls[0]["index"] == "support-search"
    bool_query = body["query"]["bool"]
    assert {"term": {"tenant_id": "tenant-acme"}} in bool_query["filter"]
    assert {"terms": {"acl_tokens": ["group:support", "tenant:tenant-acme"]}} in bool_query["filter"]
    assert {"term": {"source_type": "ticket"}} in bool_query["filter"]
    assert {"term": {"source_id": {"value": "A-1001", "boost": 8.0}}} in bool_query["should"]
    assert {"term": {"document_id": {"value": "A-1001", "boost": 6.0}}} in bool_query["should"]
    assert {"match_phrase": {"title": {"query": "A-1001", "boost": 4.0}}} in bool_query["should"]
    assert body["query"]["bool"]["must"][0]["multi_match"]["fields"] == ["title^3", "text"]
    assert body["highlight"]["fields"]["text"]["fragment_size"] == 240


@pytest.mark.asyncio
async def test_lexical_normalization_drops_cross_tenant_and_acl_inaccessible_hits():
    from app.search.models import SearchMode, SearchRequest

    client = FakeSearchClient(
        {
            "hits": {
                "total": 1,
                "hits": [
                    _hit(),
                    _hit("other-tenant", tenant_id="tenant-zen"),
                    _hit("finance-only", acl_tokens=("tenant:tenant-acme", "group:finance")),
                ],
            }
        }
    )
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    response = await provider.search(
        SearchRequest(text="export", scope=_scope(), mode=SearchMode.LEXICAL)
    )

    assert [result.document_id for result in response.results] == ["acme-ticket-1001"]
    assert all(result.tenant_id == "tenant-acme" for result in response.results)


@pytest.mark.asyncio
async def test_provider_requires_query_vector_for_vector_modes_and_accepts_cursor():
    from app.search.models import SearchMode, SearchRequest

    provider = OpenSearchProvider(config=_config(), client=FakeSearchClient({}))
    await provider.connect()

    with pytest.raises(ValueError, match="requires query_vector"):
        await provider.search(SearchRequest(text="export", scope=_scope(), mode=SearchMode.HYBRID))


@pytest.mark.asyncio
async def test_vector_query_compiles_knn_filter_and_normalizes_result():
    from app.search.models import SearchMode, SearchRequest

    client = FakeSearchClient({"hits": {"total": {"value": 1}, "hits": [_hit(score=0.91)]}})
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    response = await provider.search(
        SearchRequest(text="export", scope=_scope(), mode=SearchMode.VECTOR, query_vector=[0.1, 0.2])
    )

    assert response.results[0].retrieval_source.value == "vector"
    assert response.results[0].vector_score == 0.91
    body = client.search_calls[0]["body"]
    assert body["query"]["knn"]["embedding"]["vector"] == [0.1, 0.2]
    assert {"term": {"tenant_id": "tenant-acme"}} in body["query"]["knn"]["embedding"]["filter"]["bool"]["filter"]


@pytest.mark.asyncio
async def test_hybrid_query_fuses_deterministically_and_paginates_lexical_results():
    from app.search.models import RetrievalSource, SearchMode, SearchRequest

    lexical_response = {
        "hits": {
            "total": {"value": 2},
            "hits": [
                {**_hit("doc-a", score=9.0), "sort": [9.0, "doc-a"]},
                {**_hit("doc-b", score=8.0), "sort": [8.0, "doc-b"]},
            ],
        }
    }
    vector_response = {
        "hits": {
            "total": {"value": 2},
            "hits": [
                {**_hit("doc-b", score=0.95), "sort": [0.95, "doc-b"]},
                {**_hit("doc-c", score=0.90), "sort": [0.90, "doc-c"]},
            ],
        }
    }
    client = SequenceSearchClient([lexical_response, vector_response])
    provider = OpenSearchProvider(config=_config(), client=client)
    await provider.connect()

    response = await provider.search(
        SearchRequest(
            text="export",
            scope=_scope(),
            mode=SearchMode.HYBRID,
            query_vector=[0.1, 0.2],
            limit=2,
        )
    )

    assert [result.document_id for result in response.results] == ["doc-b", "doc-a"]
    assert all(result.retrieval_source == RetrievalSource.HYBRID for result in response.results)
    assert response.results[0].fusion_score > response.results[1].fusion_score
    assert response.total == 3
    assert response.next_cursor
    assert client.search_calls[0]["body"]["size"] == 50
    assert client.search_calls[1]["body"]["query"]["knn"]

    next_client = SequenceSearchClient([lexical_response, vector_response])
    next_provider = OpenSearchProvider(config=_config(), client=next_client)
    await next_provider.connect()
    next_page = await next_provider.search(
        SearchRequest(
            text="export",
            scope=_scope(),
            mode=SearchMode.HYBRID,
            query_vector=[0.1, 0.2],
            limit=1,
            cursor=response.next_cursor,
        )
    )
    assert next_page.results[0].document_id == "doc-c"
    assert next_page.total == 3


@pytest.mark.asyncio
async def test_lexical_cursor_is_encoded_and_sent_as_search_after():
    from app.search.models import SearchMode, SearchRequest

    first_client = FakeSearchClient(
        {"hits": {"total": {"value": 2}, "hits": [{**_hit(), "sort": [8.25, "acme-ticket-1001"]}]}}
    )
    provider = OpenSearchProvider(config=_config(), client=first_client)
    await provider.connect()
    first = await provider.search(
        SearchRequest(text="export", scope=_scope(), mode=SearchMode.LEXICAL, limit=1)
    )
    assert first.next_cursor

    second_client = FakeSearchClient({"hits": {"total": {"value": 1}, "hits": []}})
    provider = OpenSearchProvider(config=_config(), client=second_client)
    await provider.connect()
    await provider.search(
        SearchRequest(
            text="export",
            scope=_scope(),
            mode=SearchMode.LEXICAL,
            cursor=first.next_cursor,
        )
    )
    assert second_client.search_calls[0]["body"]["search_after"] == [8.25, "acme-ticket-1001"]
