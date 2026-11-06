"""RO-2: OpenSearchIndexer maps chunk rows to support documents and writes them safely (fake provider, no cluster)."""

from __future__ import annotations

import pickle
from types import SimpleNamespace

import pytest

from pipelines.ingestion.indexing.sinks import parse_sink_names

# The indexer imports app.config, which reads the environment once. Importing it at collection time would run
# before other test modules set their environment, so these names are bound when the first test runs instead.
IndexerError = OpenSearchIndexer = PROVIDER_NAME = SupportSearchDocument = None


@pytest.fixture(autouse=True, scope="module")
def _late_imports():
    from app.search.schema import SupportSearchDocument as document
    from pipelines.ingestion.indexing.opensearch import PROVIDER_NAME as provider
    from pipelines.ingestion.indexing.opensearch import IndexerError as error
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer as indexer

    globals().update(
        IndexerError=error, OpenSearchIndexer=indexer, PROVIDER_NAME=provider, SupportSearchDocument=document
    )


DIM = 4


def _row(text="reset your password", filename="guide.pdf", page=1, vector=None, **extra):
    return {
        "text": text,
        "vector": [0.1, 0.2, 0.3, 0.4] if vector is None else vector,
        "metadata": {
            "filename": filename,
            "page_number": page,
            "chunk_index": 0,
            "chunk_hash": "abc",
            "ingested_at": "now",
        },
        **extra,
    }


class FakeProvider:
    instances: list["FakeProvider"] = []

    def __init__(self, failures=None):
        self.specs, self.upserts, self.closed = [], [], False
        self.connected = False
        self.failures = failures  # callable(call_number, docs) -> list of error namespaces
        self.calls = 0
        FakeProvider.instances.append(self)

    async def connect(self):
        self.connected = True

    async def ensure_index(self, spec):
        self.specs.append(spec)

    async def upsert(self, documents, *, index=None):
        self.calls += 1
        self.upserts.append((index, list(documents)))
        errors = self.failures(self.calls, documents) if self.failures else []
        return SimpleNamespace(
            attempted=len(documents), succeeded=len(documents) - len(errors), failed=len(errors), errors=errors
        )

    async def close(self):
        self.closed = True


def _indexer(provider=None, **kw):
    FakeProvider.instances.clear()
    factory = (lambda: provider) if provider else FakeProvider
    kw.setdefault("sleep", lambda _s: None)
    return OpenSearchIndexer(
        index="chunks-test", dimensions=DIM, embedding_model_version="m1", provider_factory=factory, **kw
    )


def test_rows_become_valid_tenant_scoped_documents_with_vectors() -> None:
    docs, skipped = _indexer().build_documents([_row()])
    (doc,) = docs
    assert skipped == 0 and isinstance(doc, SupportSearchDocument)
    assert doc.source_type == "file_chunk" and doc.provider == PROVIDER_NAME and doc.tenant_id == "default"
    assert doc.acl_tokens == ("tenant:default",)
    assert doc.vector == (0.1, 0.2, 0.3, 0.4) and doc.embedding_model_version == "m1"
    assert doc.metadata["filename"] == "guide.pdf" and "ingested_at" not in doc.metadata
    assert doc.source_id.startswith("guide.pdf:chunk:p1:")


def test_ids_are_stable_across_runs_and_change_with_content() -> None:
    a = _indexer().build_documents([_row()])[0][0]
    b = _indexer().build_documents([_row()])[0][0]
    c = _indexer().build_documents([_row(text="different text")])[0][0]
    assert a.document_id == b.document_id and a.content_hash == b.content_hash
    assert a.document_id != c.document_id


def test_tenant_comes_from_the_indexer() -> None:
    indexer = OpenSearchIndexer("acme", index="i", dimensions=DIM, provider_factory=FakeProvider)
    doc = indexer.build_documents([_row()])[0][0]
    assert doc.tenant_id == "acme" and doc.acl_tokens == ("tenant:acme",) and doc.document_id.startswith("acme:")


def test_images_and_rows_without_a_vector_or_text_are_skipped_and_counted() -> None:
    rows = [
        _row(),
        _row(content_type="image"),
        _row(vector=[]),
        {"text": "x", "metadata": {"filename": "f"}},
        _row(text="  "),
    ]
    docs, skipped = _indexer().build_documents(rows)
    assert len(docs) == 1 and skipped == 4


def test_a_wrong_dimension_rejects_the_whole_batch_before_any_write() -> None:
    indexer = _indexer()
    with pytest.raises(IndexerError, match="4 dimensions|expects 4"):
        indexer.write([_row(), _row(text="two", vector=[1.0, 2.0])])
    assert FakeProvider.instances == []  # no provider was even created


def test_a_chunk_without_a_filename_is_refused() -> None:
    with pytest.raises(IndexerError, match="filename"):
        _indexer().write([{"text": "x", "vector": [1, 2, 3, 4], "metadata": {}}])


def test_write_ensures_the_index_upserts_to_it_and_closes() -> None:
    provider = FakeProvider()
    report = _indexer(provider).write([_row(), _row(text="second"), _row(content_type="image")])
    assert (report.received, report.indexed, report.skipped) == (3, 2, 1)
    assert provider.connected and provider.closed
    assert provider.specs[0].generation == "chunks-test" and provider.specs[0].vector_dimensions == DIM
    assert [(index, len(docs)) for index, docs in provider.upserts] == [("chunks-test", 2)]


def test_an_empty_or_all_skipped_batch_touches_nothing() -> None:
    assert _indexer().write([]).indexed == 0
    assert _indexer().write([_row(content_type="image")]).skipped == 1
    assert FakeProvider.instances == []


def test_large_batches_are_split() -> None:
    provider = FakeProvider()
    _indexer(provider).write([_row(text=f"chunk {i}") for i in range(450)])
    assert [len(docs) for _, docs in provider.upserts] == [200, 200, 50]


def _err(document_id, retryable, code="x"):
    return SimpleNamespace(document_id=document_id, code=code, retryable=retryable, message="secret body text")


def test_a_permanent_failure_raises_with_ids_and_codes_but_no_text() -> None:
    provider = FakeProvider(failures=lambda n, docs: [_err(docs[0].document_id, False, "mapper_parsing_exception")])
    with pytest.raises(IndexerError) as info:
        _indexer(provider).write([_row()])
    message = str(info.value)
    assert "mapper_parsing_exception" in message and "default:" in message and "secret body text" not in message
    assert provider.closed and provider.calls == 1  # not retried


def test_retryable_failures_are_retried_for_only_the_failed_documents() -> None:
    def failures(call, docs):
        return [_err(docs[0].document_id, True, "429")] if call == 1 else []

    provider = FakeProvider(failures=failures)
    _indexer(provider).write([_row(text="a"), _row(text="b")])
    assert [len(docs) for _, docs in provider.upserts] == [2, 1]


def test_retries_are_bounded() -> None:
    provider = FakeProvider(failures=lambda n, docs: [_err(docs[0].document_id, True, "429")])
    with pytest.raises(IndexerError, match="1 documents failed"):
        _indexer(provider).write([_row()])
    assert provider.calls == 3 and provider.closed


def test_the_indexer_pickles_for_ray_workers() -> None:
    indexer = OpenSearchIndexer(index="i", dimensions=DIM)
    clone = pickle.loads(pickle.dumps(indexer))
    assert clone.index == "i" and clone.dimensions == DIM


def test_an_index_name_is_required(monkeypatch) -> None:
    monkeypatch.delenv("INGEST_OPENSEARCH_INDEX", raising=False)
    with pytest.raises(IndexerError, match="INGEST_OPENSEARCH_INDEX"):
        OpenSearchIndexer()


def test_the_default_sink_is_qdrant_only_and_names_are_validated() -> None:
    assert parse_sink_names({}) == ["qdrant"]
    assert parse_sink_names({"INGEST_VECTOR_SINKS": " Qdrant , opensearch,qdrant"}) == ["qdrant", "opensearch"]
    for bad in ("", "pinecone", "qdrant,solr"):
        with pytest.raises(ValueError):
            parse_sink_names({"INGEST_VECTOR_SINKS": bad})
