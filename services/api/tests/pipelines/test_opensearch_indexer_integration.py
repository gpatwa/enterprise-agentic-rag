"""RO-3: OpenSearchIndexer against a real local OpenSearch node. Opt-in; never runs in unit CI.

    docker compose --profile search up -d opensearch
    cd services/api && OPENSEARCH_INTEGRATION=1 OPENSEARCH_ENABLED=true OPENSEARCH_URL=http://localhost:9200 \
        python -m pytest tests/pipelines/test_opensearch_indexer_integration.py -q

Each test uses its own uniquely named index and deletes it afterwards.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest

pytestmark = [
    pytest.mark.opensearch_integration,
    pytest.mark.skipif(
        os.getenv("OPENSEARCH_INTEGRATION", "").lower() not in {"1", "true", "yes"},
        reason="set OPENSEARCH_INTEGRATION=1 to run against a local OpenSearch node",
    ),
]

DIM = 8


def _url() -> str:
    from app.config import settings

    return settings.get_opensearch_url()


def _vector(i: int) -> list[float]:
    return [((i + k) % 7) / 7.0 + 0.01 for k in range(DIM)]


def _rows(prefix: str, n: int, filename: str = "manual.pdf") -> list[dict]:
    return [
        {
            "text": f"{prefix} chunk {i} explains how to reset a password",
            "vector": _vector(i),
            "metadata": {"filename": filename, "page_number": i // 10, "chunk_index": i, "chunk_hash": f"h{i}"},
        }
        for i in range(n)
    ]


@pytest.fixture
def index():
    import httpx

    name = f"ro3-{uuid.uuid4().hex[:10]}"
    yield name
    httpx.delete(f"{_url()}/{name}", timeout=30)


def _count(index: str) -> int:
    import httpx

    httpx.post(f"{_url()}/{index}/_refresh", timeout=30).raise_for_status()
    return int(httpx.get(f"{_url()}/{index}/_count", timeout=30).json()["count"])


def _indexer(index: str, tenant: str = "acme", dimensions: int = DIM):
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

    return OpenSearchIndexer(tenant, index=index, dimensions=dimensions, embedding_model_version="ro3")


def _search(index: str, tenant: str, text: str):
    from app.config import settings
    from app.search.models import SearchMode, SearchRequest, SearchScope
    from app.search.opensearch import OpenSearchProvider

    async def run():
        provider = OpenSearchProvider(config=settings)
        await provider.connect()
        try:
            # The provider searches the configured alias; point it at this test's index.
            provider.config = type(
                "Cfg",
                (),
                {
                    **{k: getattr(settings, k) for k in dir(settings) if k.isupper()},
                    "OPENSEARCH_INDEX_ALIAS": index,
                    "get_opensearch_url": settings.get_opensearch_url,
                },
            )()
            scope = SearchScope(tenant_id=tenant, principal_id="p", purpose="search", acl_tokens=(f"tenant:{tenant}",))
            return await provider.search(SearchRequest(text=text, scope=scope, mode=SearchMode.LEXICAL, limit=50))
        finally:
            await provider.close()

    return asyncio.run(run())


def test_rows_are_indexed_with_the_support_schema_and_a_rerun_changes_nothing(index) -> None:
    import httpx

    indexer = _indexer(index)
    first = indexer.write(_rows("alpha", 30))
    assert (first.indexed, first.skipped) == (30, 0) and _count(index) == 30
    indexer.write(_rows("alpha", 30))
    assert _count(index) == 30

    hit = httpx.get(f"{_url()}/{index}/_search", params={"size": 1}, timeout=30).json()["hits"]["hits"][0]["_source"]
    assert hit["source_type"] == "file_chunk" and hit["tenant_id"] == "acme" and hit["acl_tokens"] == ["tenant:acme"]
    assert len(hit["embedding"]) == DIM and hit["embedding_model_version"] == "ro3"
    assert hit["schema_version"] == "support-search-v1" and len(hit["content_hash"]) == 64


def test_a_second_tenant_cannot_see_the_first_tenants_chunks(index) -> None:
    _indexer(index, "acme").write(_rows("acmeonly", 5))
    _indexer(index, "beta").write(_rows("betaonly", 5))
    assert _count(index) == 10

    acme = _search(index, "acme", "acmeonly")
    beta_for_acme_text = _search(index, "beta", "acmeonly")
    assert acme.results and all(r.tenant_id == "acme" for r in acme.results)
    assert beta_for_acme_text.results == ()


def test_a_dimension_mismatch_against_an_existing_index_writes_nothing(index) -> None:
    _indexer(index).write(_rows("alpha", 3))
    with pytest.raises(ValueError, match="field definition changed: embedding"):
        _indexer(index, dimensions=16).write([{**row, "vector": row["vector"] * 2} for row in _rows("beta", 3)])
    assert _count(index) == 3
