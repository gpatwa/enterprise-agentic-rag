"""The REAL ``QdrantIndexer`` and ``OpenSearchIndexer`` as Ray Data sinks, on a real local Ray. Opt-in.

Needs ``ray[data]``, ``pyarrow``, ``qdrant-client``, ``opensearch-py[async]`` and two local services. Export the
settings in the shell BEFORE starting pytest: Ray workers inherit the environment of the process that starts Ray.

    docker run -d --name par-support-qdrant -p 127.0.0.1:6340:6333 qdrant/qdrant:v1.7.3
    docker run -d --name par-support-os -p 127.0.0.1:9220:9200 -e discovery.type=single-node \
        -e DISABLE_SECURITY_PLUGIN=true -e DISABLE_INSTALL_DEMO_CONFIG=true \
        -e "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m" opensearchproject/opensearch:2.15.0
    cd services/api && RAY_SINK_INTEGRATION=1 QDRANT_HOST=127.0.0.1 QDRANT_PORT=6340 OPENSEARCH_ENABLED=true \
        OPENSEARCH_URL=http://127.0.0.1:9220 PYTHONPATH=.:../.. \
        python -m pytest tests/pipelines/test_ray_real_sinks_integration.py -q

Every test creates its own Qdrant collection and OpenSearch index and deletes them afterwards.
"""

from __future__ import annotations

import os
import uuid

import pytest

pytestmark = [
    pytest.mark.opensearch_integration,
    pytest.mark.skipif(
        os.getenv("RAY_SINK_INTEGRATION", "").lower() not in {"1", "true", "yes"},
        reason="set RAY_SINK_INTEGRATION=1 to run the real sinks on a real Ray against local services",
    ),
]

DIM = 8
ROWS = 24


def _vector(i: int) -> list[float]:
    return [((i + k) % 7) / 7.0 + 0.01 for k in range(DIM)]


def _rows(prefix: str = "doc", filename: str = "manual.pdf", n: int = ROWS) -> list[dict]:
    return [
        {
            "text": f"{prefix} chunk {i} explains how to reset a password",
            "vector": _vector(i),
            "content_type": "text",
            "metadata": {"filename": filename, "page_number": i // 10, "chunk_index": i, "chunk_hash": f"h{i}"},
        }
        for i in range(n)
    ]


@pytest.fixture(scope="module")
def ray_cluster():
    import ray

    ray.init(num_cpus=2, include_dashboard=False, logging_level="ERROR", ignore_reinit_error=True)
    yield ray
    ray.shutdown()


def _dataset(rows: list[dict], blocks: int = 4):
    import ray.data

    # Several blocks make Ray run several write tasks at once, as a real job does.
    return ray.data.from_items(rows, override_num_blocks=blocks)


# ----- Qdrant -----------------------------------------------------------------------------------------------


@pytest.fixture
def qdrant_collection(monkeypatch):
    from qdrant_client import QdrantClient
    from qdrant_client.http import models

    name = f"par-ray-{uuid.uuid4().hex[:10]}"
    client = QdrantClient(host=os.environ["QDRANT_HOST"], port=int(os.environ.get("QDRANT_PORT", "6333")))
    client.create_collection(name, vectors_config=models.VectorParams(size=DIM, distance=models.Distance.COSINE))
    monkeypatch.setenv("QDRANT_COLLECTION", name)
    yield name, client
    client.delete_collection(name)


def _qdrant_count(client, collection: str, tenant: str | None = None) -> int:
    from qdrant_client.http import models

    flt = None
    if tenant:
        flt = models.Filter(must=[models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant))])
    return client.count(collection, count_filter=flt, exact=True).count


def test_real_qdrant_indexer_writes_every_row_idempotently_and_tags_the_tenant(ray_cluster, qdrant_collection) -> None:
    from pipelines.ingestion.indexing.qdrant import QdrantIndexer
    from pipelines.ingestion.indexing.ray_sink import write_rows

    collection, client = qdrant_collection
    write_rows(_dataset(_rows()), QdrantIndexer("acme"))
    assert _qdrant_count(client, collection) == ROWS

    write_rows(_dataset(_rows()), QdrantIndexer("acme"))  # a re-run of the same job
    assert _qdrant_count(client, collection) == ROWS, "a re-run must upsert in place, not add a second copy"

    write_rows(_dataset(_rows()), QdrantIndexer("beta"))  # same file, other tenant
    assert _qdrant_count(client, collection, "acme") == ROWS
    assert _qdrant_count(client, collection, "beta") == ROWS
    assert _qdrant_count(client, collection) == 2 * ROWS

    points, _ = client.scroll(collection, limit=100, with_payload=True)
    assert {p.payload["tenant_id"] for p in points} == {"acme", "beta"}
    assert all(p.payload["filename"] == "manual.pdf" for p in points)


# ----- OpenSearch -------------------------------------------------------------------------------------------


def _url() -> str:
    from app.config import settings

    return settings.get_opensearch_url()


@pytest.fixture
def os_index():
    import httpx

    name = f"par-ray-{uuid.uuid4().hex[:10]}"
    yield name
    httpx.delete(f"{_url()}/{name}", timeout=30)


def _os_count(index: str, tenant: str | None = None) -> int:
    import httpx

    httpx.post(f"{_url()}/{index}/_refresh", timeout=30).raise_for_status()
    body = {"query": {"term": {"tenant_id": tenant}}} if tenant else {"query": {"match_all": {}}}
    return int(httpx.post(f"{_url()}/{index}/_count", json=body, timeout=30).json()["count"])


def _os_indexer(index: str, tenant: str):
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

    return OpenSearchIndexer(tenant, index=index, dimensions=DIM, embedding_model_version="par-ray")


def test_real_opensearch_indexer_writes_every_row_idempotently_and_tags_the_tenant(ray_cluster, os_index) -> None:
    import httpx

    from pipelines.ingestion.indexing.ray_sink import write_rows

    # A fresh index and four parallel write tasks: they all race to create it.
    write_rows(_dataset(_rows()), _os_indexer(os_index, "acme"))
    assert _os_count(os_index) == ROWS

    write_rows(_dataset(_rows()), _os_indexer(os_index, "acme"))
    assert _os_count(os_index) == ROWS, "a re-run must upsert in place, not add a second copy"

    write_rows(_dataset(_rows()), _os_indexer(os_index, "beta"))
    assert _os_count(os_index, "acme") == ROWS
    assert _os_count(os_index, "beta") == ROWS
    assert _os_count(os_index) == 2 * ROWS

    hits = httpx.post(
        f"{_url()}/{os_index}/_search", json={"size": 100, "query": {"match_all": {}}}, timeout=30
    ).json()["hits"]["hits"]
    for hit in hits:
        source = hit["_source"]
        assert source["source_type"] == "file_chunk"
        assert source["acl_tokens"] == [f"tenant:{source['tenant_id']}"]
        assert len(source["embedding"]) == DIM
    assert {hit["_source"]["tenant_id"] for hit in hits} == {"acme", "beta"}


def test_a_worker_side_dimension_failure_reaches_the_driver_readably(ray_cluster, os_index) -> None:
    from pipelines.ingestion.indexing.ray_sink import write_rows

    rows = _rows(n=4)
    rows[2]["vector"] = [0.1] * (DIM + 1)
    with pytest.raises(Exception, match="dimensions"):
        write_rows(_dataset(rows, blocks=1), _os_indexer(os_index, "acme"))
    assert _os_count_or_zero(os_index) == 0


def _os_count_or_zero(index: str) -> int:
    import httpx

    response = httpx.post(f"{_url()}/{index}/_refresh", timeout=30)
    return 0 if response.status_code == 404 else _os_count(index)
