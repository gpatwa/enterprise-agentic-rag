"""Ray ships sink objects to workers, so every sink must pickle. Needs no running service.

Found by running the real sinks on a real Ray: ``QdrantIndexer`` built its ``QdrantClient`` in ``__init__`` and
the client holds a thread lock, so ``write_rows(dataset, QdrantIndexer())`` failed before writing anything.
"""

from __future__ import annotations

import pickle

import pytest

pytest.importorskip("qdrant_client")

from pipelines.ingestion.indexing.qdrant import QdrantIndexer  # noqa: E402
from pipelines.ingestion.indexing.ray_sink import RowDatasink  # noqa: E402


class FakeQdrant:
    """Stands in for a live client: unpicklable, like the real one."""

    def __init__(self) -> None:
        import threading

        self.lock = threading.RLock()
        self.points: list = []

    def upsert(self, *, collection_name, points):
        self.points.extend(points)


def _roundtrip(obj):
    restored = pickle.loads(pickle.dumps(obj))
    try:
        import cloudpickle
    except ImportError:  # pragma: no cover
        return restored
    return cloudpickle.loads(cloudpickle.dumps(obj))


def test_qdrant_indexer_pickles_before_and_after_it_has_a_live_client(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    indexer = QdrantIndexer("acme")
    restored = _roundtrip(indexer)
    assert (restored.tenant_id, restored.collection_name) == ("acme", indexer.collection_name)

    indexer.client = FakeQdrant()  # a client in use must not travel with the object
    restored = _roundtrip(RowDatasink(indexer)).sink
    assert restored.tenant_id == "acme" and restored._client is None


def test_qdrant_client_is_built_lazily_on_first_use(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    monkeypatch.setenv("QDRANT_PORT", "6340")
    indexer = QdrantIndexer("acme")
    assert indexer._client is None
    assert indexer.client is indexer.client  # one client per process, reused


def test_opensearch_indexer_pickles(monkeypatch) -> None:
    # Imported here: importing the indexer loads app.config, which must not happen at collection time.
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

    indexer = OpenSearchIndexer("acme", index="idx", dimensions=8, embedding_model_version="v")
    restored = _roundtrip(RowDatasink(indexer)).sink
    assert (restored.tenant_id, restored.index, restored.dimensions) == ("acme", "idx", 8)


def _rows(n: int = 3, filename: str = "a.pdf", text: str = "chunk") -> list[dict]:
    return [
        {
            "text": f"{text} {i}",
            "vector": [0.1 * (i + 1)] * 4,
            "content_type": "text",
            "metadata": {"filename": filename, "page_number": 0, "chunk_index": i},
        }
        for i in range(n)
    ]


def test_qdrant_point_ids_are_deterministic_so_a_rerun_upserts_in_place(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    first, second, other_tenant = QdrantIndexer("acme"), QdrantIndexer("acme"), QdrantIndexer("beta")
    for indexer in (first, second, other_tenant):
        indexer.client = FakeQdrant()
        indexer.write(_rows())
    ids = lambda indexer: [p.id for p in indexer.client.points]  # noqa: E731
    assert ids(first) == ids(second) and len(set(ids(first))) == 3
    assert set(ids(first)).isdisjoint(ids(other_tenant)), "the same file for another tenant must be a different point"
    assert {p.payload["tenant_id"] for p in first.client.points} == {"acme"}


def test_qdrant_point_id_changes_with_the_text_the_file_and_the_page(monkeypatch) -> None:
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    indexer = QdrantIndexer("acme")
    indexer.client = FakeQdrant()
    base = _rows(1)
    moved = _rows(1, filename="b.pdf")
    edited = _rows(1, text="edited chunk")
    paged = _rows(1)
    paged[0]["metadata"]["page_number"] = 7
    indexer.write(base + moved + edited + paged)
    assert len({p.id for p in indexer.client.points}) == 4


def test_qdrant_accepts_numpy_vectors_and_skips_empty_ones(monkeypatch) -> None:
    np = pytest.importorskip("numpy")
    monkeypatch.setenv("QDRANT_HOST", "127.0.0.1")
    indexer = QdrantIndexer("acme")
    indexer.client = FakeQdrant()
    rows = _rows(3)
    rows[0]["vector"] = np.array([0.5, 0.5, 0.5, 0.5])
    rows[1]["vector"] = np.array([])
    rows[2]["vector"] = None
    indexer.write(rows)
    assert len(indexer.client.points) == 1
    assert list(indexer.client.points[0].vector) == [0.5, 0.5, 0.5, 0.5]


def test_neo4j_indexer_does_not_open_or_pickle_a_driver(monkeypatch) -> None:
    """``neo4j`` may not be installed where this runs, so a stand-in module is used; the real driver is not tried."""
    import sys
    import threading
    import types

    created: list[tuple] = []

    class FakeDriver:
        def __init__(self) -> None:
            self.lock = threading.RLock()  # unpicklable, like the real driver

    fake = types.ModuleType("neo4j")
    fake.GraphDatabase = types.SimpleNamespace(driver=lambda uri, auth: created.append((uri, auth)) or FakeDriver())
    monkeypatch.setitem(sys.modules, "neo4j", fake)
    module_name = "pipelines.ingestion.indexing.neo4j"
    previous = sys.modules.pop(module_name, None)
    try:
        from pipelines.ingestion.indexing.neo4j import Neo4jIndexer

        indexer = Neo4jIndexer("acme")
        assert created == [], "constructing the sink must not open a connection"
        restored = _roundtrip(indexer)
        assert restored.tenant_id == "acme" and restored._driver is None
        assert restored.driver is restored.driver and len(created) == 1
        assert _roundtrip(restored)._driver is None  # a driver in use does not travel either
    finally:  # leave no module bound to the stand-in for tests that run later
        sys.modules.pop(module_name, None)
        if previous is not None:
            sys.modules[module_name] = previous
