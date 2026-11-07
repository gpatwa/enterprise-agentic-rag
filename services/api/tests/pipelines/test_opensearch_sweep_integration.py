"""Stale-chunk sweep against a real local OpenSearch node. Opt-in; never runs in unit CI.

    docker run -d --name par-support-os -p 127.0.0.1:9220:9200 -e discovery.type=single-node \
        -e DISABLE_SECURITY_PLUGIN=true -e DISABLE_INSTALL_DEMO_CONFIG=true \
        -e "OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m" opensearchproject/opensearch:2.15.0
    cd services/api && OPENSEARCH_INTEGRATION=1 OPENSEARCH_ENABLED=true OPENSEARCH_URL=http://127.0.0.1:9220 \
        PYTHONPATH=.:../.. python -m pytest tests/pipelines/test_opensearch_sweep_integration.py -q

Each test uses its own uniquely named index and deletes it afterwards.
"""

from __future__ import annotations

import os
import time
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


def _rows(filename: str, texts: list[str]) -> list[dict]:
    return [
        {
            "text": text,
            "vector": _vector(i),
            "metadata": {"filename": filename, "page_number": 0, "chunk_index": i, "chunk_hash": f"h{i}"},
        }
        for i, text in enumerate(texts)
    ]


@pytest.fixture
def index():
    import httpx

    name = f"par-sweep-{uuid.uuid4().hex[:10]}"
    yield name
    httpx.delete(f"{_url()}/{name}", timeout=30)


def _indexer(index: str, tenant: str = "acme", **kw):
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

    return OpenSearchIndexer(tenant, index=index, dimensions=DIM, embedding_model_version="sweep", **kw)


def _docs(index: str, **term) -> list[dict]:
    import httpx

    httpx.post(f"{_url()}/{index}/_refresh", timeout=30).raise_for_status()
    must = [{"term": {k: v}} for k, v in term.items()] or [{"match_all": {}}]
    body = {"size": 1000, "query": {"bool": {"filter": must}}}
    hits = httpx.post(f"{_url()}/{index}/_search", json=body, timeout=30).json()["hits"]["hits"]
    return [hit["_source"] for hit in hits]


def _texts(index: str, **term) -> set[str]:
    return {doc["text"] for doc in _docs(index, **term)}


def _write_other_provider_doc(index: str, tenant: str, title: str) -> None:
    import asyncio

    from app.config import settings
    from app.search.models import SearchIndexSpec
    from app.search.opensearch import OpenSearchProvider
    from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION
    from app.search.support_mapper import map_file_chunk

    document = map_file_chunk(
        tenant_id=tenant,
        provider="postgres-sync",
        file_id=title,
        chunk_key="p0:other",
        title=title,
        text="belongs to another provider",
        embedding_model_version="sweep",
    ).model_copy(update={"vector": tuple(_vector(1))})

    async def run():
        provider = OpenSearchProvider(config=settings)
        await provider.connect()
        try:
            await provider.ensure_index(
                SearchIndexSpec(
                    alias=index,
                    generation=index,
                    schema_version=SUPPORT_SEARCH_SCHEMA_VERSION,
                    vector_dimensions=DIM,
                    embedding_model_version="sweep",
                )
            )
            await provider.upsert([document], index=index)
        finally:
            await provider.close()

    asyncio.run(run())


V1 = [f"v1 chunk {i} explains the reset" for i in range(10)]
V2 = V1[:4] + ["v2 brand new first", "v2 brand new second"]


def test_editing_a_file_removes_only_that_files_old_chunks_for_that_tenant_and_provider(index) -> None:
    other = [f"other file chunk {i}" for i in range(5)]
    first = _indexer(index, sweep=True, run_id="run-1")
    first.write(_rows("manual.pdf", V1) + _rows("other.pdf", other))
    _indexer(index, "beta", sweep=True, run_id="run-b").write(_rows("manual.pdf", V1))
    _write_other_provider_doc(index, "acme", "manual.pdf")
    assert first.finalize().deleted == 0  # first ingest: nothing is stale
    assert len(_docs(index)) == 10 + 5 + 10 + 1

    time.sleep(0.05)
    second = _indexer(index, sweep=True, run_id="run-2")
    second.write(_rows("manual.pdf", V2))
    assert (
        len(_docs(index, tenant_id="acme", provider="ray-ingest", **{"title.keyword": "manual.pdf"})) == 10 + 2
    )  # before sweep
    report = second.finalize()

    assert (report.files, report.deleted) == (1, 6)
    acme_manual = _docs(index, tenant_id="acme", provider="ray-ingest", **{"title.keyword": "manual.pdf"})
    assert {d["text"] for d in acme_manual} == set(V2)
    assert all("ingest-run:run-2" in d["tags"] for d in acme_manual), "kept chunks carry the new run's stamp"
    # Untouched: a file the run did not write, the other tenant's identically named file, another provider's chunk.
    assert _texts(index, tenant_id="acme", **{"title.keyword": "other.pdf"}) == set(other)
    assert _texts(index, tenant_id="beta") == set(V1)
    assert _texts(index, provider="postgres-sync") == {"belongs to another provider"}


def test_chunks_written_before_run_stamps_existed_are_swept_too(index) -> None:
    _indexer(index).write(_rows("manual.pdf", V1))  # sweep off: no stamp, no updated_at
    assert all(not d["tags"] and d["updated_at"] is None for d in _docs(index))

    time.sleep(0.05)
    run = _indexer(index, sweep=True, run_id="run-1")
    run.write(_rows("manual.pdf", V2))
    assert run.finalize().deleted == 6
    assert _texts(index) == set(V2)


def test_a_chunk_written_after_this_run_began_is_never_deleted(index) -> None:
    older = _indexer(index, sweep=True, run_id="run-a")  # run A begins ...
    time.sleep(0.05)
    newer = _indexer(index, sweep=True, run_id="run-b")  # ... run B begins and finishes with a different version
    newer.write(_rows("manual.pdf", ["b version one", "b version two"]))
    older.write(_rows("manual.pdf", V2))  # ... then run A finishes writing and sweeps
    assert older.finalize().deleted == 0
    assert {"b version one", "b version two"} <= _texts(index, tenant_id="acme")


def test_a_sweep_over_the_delete_cap_is_refused_and_deletes_nothing(index) -> None:
    from app.search.sweep import SweepRefused

    _indexer(index, sweep=True, run_id="run-1").write(_rows("manual.pdf", V1))
    time.sleep(0.05)
    run = _indexer(index, sweep=True, run_id="run-2", max_sweep_documents=3)
    run.write(_rows("manual.pdf", V2))
    with pytest.raises(SweepRefused, match="more than 3 chunks"):
        run.finalize()
    assert len(_docs(index)) == 10 + 2  # all ten old chunks are still there, plus the two new ones


def test_without_the_flag_nothing_is_stamped_and_old_chunks_stay(index) -> None:
    _indexer(index).write(_rows("manual.pdf", V1))
    run = _indexer(index)
    run.write(_rows("manual.pdf", V2))
    assert run.finalize() is None
    assert len(_docs(index)) == 12 and all(not d["tags"] for d in _docs(index))


def test_a_run_that_wrote_nothing_deletes_nothing(index) -> None:
    _indexer(index, sweep=True, run_id="run-1").write(_rows("manual.pdf", V1))
    time.sleep(0.05)
    empty = _indexer(index, sweep=True, run_id="run-2")  # e.g. every file failed to parse into chunks
    report = empty.finalize()
    assert (report.files, report.deleted) == (0, 0)
    assert _texts(index) == set(V1)


def test_a_missing_index_fails_the_sweep_instead_of_deleting_elsewhere(index) -> None:
    from app.search.errors import OpenSearchError

    run = _indexer(index, sweep=True, run_id="run-1")
    with pytest.raises(OpenSearchError):
        run.finalize()
