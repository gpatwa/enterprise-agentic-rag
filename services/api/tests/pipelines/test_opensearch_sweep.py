"""Stale-chunk sweep in the OpenSearch indexer: off by default, stamped when on, deletes only what the provider lists
for this tenant, and fails closed. Fake provider only (the real node is covered in the integration tests)."""

from __future__ import annotations

import pickle
from datetime import timezone
from types import SimpleNamespace

import pytest

DIM = 4


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for name in ("INGEST_OPENSEARCH_SWEEP", "INGEST_RUN_ID", "INGEST_OPENSEARCH_SWEEP_MAX_DELETE"):
        monkeypatch.delenv(name, raising=False)


def _row(text="reset your password", filename="guide.pdf", page=1):
    return {
        "text": text,
        "vector": [0.1, 0.2, 0.3, 0.4],
        "metadata": {"filename": filename, "page_number": page, "chunk_index": 0, "chunk_hash": "abc"},
    }


class SweepProvider:
    instances: list["SweepProvider"] = []

    def __init__(self, stale=("doc-1", "doc-2"), files=("guide.pdf",), find_error=None, failed=()):
        self.stale, self.files, self.find_error, self.failed = list(stale), list(files), find_error, list(failed)
        self.find_calls, self.delete_calls, self.upserts = [], [], []
        self.connected = self.closed = False
        SweepProvider.instances.append(self)

    async def connect(self):
        self.connected = True

    async def ensure_index(self, spec):
        pass

    async def upsert(self, documents, *, index=None):
        self.upserts.extend(documents)
        return SimpleNamespace(attempted=len(documents), succeeded=len(documents), failed=0, errors=[])

    async def find_stale_file_chunks(self, **kwargs):
        self.find_calls.append(kwargs)
        if self.find_error:
            raise self.find_error
        from app.search.sweep import StaleFileChunks

        return StaleFileChunks(document_ids=tuple(self.stale), files=tuple(self.files))

    async def delete(self, ids, *, scope, index=None):
        self.delete_calls.append((list(ids), scope, index))
        errors = [SimpleNamespace(document_id=i, code="bulk_delete") for i in self.failed]
        return SimpleNamespace(attempted=len(ids), succeeded=len(ids) - len(errors), failed=len(errors), errors=errors)

    async def close(self):
        self.closed = True


def _indexer(provider=None, tenant="acme", **kw):
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

    SweepProvider.instances.clear()
    return OpenSearchIndexer(
        tenant,
        index="chunks-test",
        dimensions=DIM,
        embedding_model_version="m1",
        provider_factory=(lambda: provider) if provider else SweepProvider,
        sleep=lambda _s: None,
        **kw,
    )


def test_the_sweep_is_off_by_default_stamps_nothing_and_never_creates_a_provider() -> None:
    indexer = _indexer()
    assert indexer.sweep is False and indexer.run_id is None
    doc = indexer.build_documents([_row()])[0][0]
    assert doc.attributes.tags == () and doc.updated_at is None
    assert indexer.finalize() is None
    assert SweepProvider.instances == []


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", "on"])
def test_the_flag_turns_it_on(monkeypatch, value) -> None:
    monkeypatch.setenv("INGEST_OPENSEARCH_SWEEP", value)
    assert _indexer().sweep is True


@pytest.mark.parametrize("value", ["", "false", "0", "no", "off"])
def test_the_flag_turns_it_off(monkeypatch, value) -> None:
    monkeypatch.setenv("INGEST_OPENSEARCH_SWEEP", value)
    assert _indexer().sweep is False


@pytest.mark.parametrize("value", ["ture", "2", "enabled"])
def test_an_unrecognised_flag_fails_at_start_instead_of_guessing(monkeypatch, value) -> None:
    monkeypatch.setenv("INGEST_OPENSEARCH_SWEEP", value)
    with pytest.raises(ValueError, match="INGEST_OPENSEARCH_SWEEP"):
        _indexer()


def test_with_the_sweep_on_every_chunk_carries_the_run_stamp_and_start_time() -> None:
    indexer = _indexer(sweep=True, run_id="job-7")
    docs, _ = indexer.build_documents([_row(), _row(text="other", page=2)])
    assert [d.attributes.tags for d in docs] == [("ingest-run:job-7",)] * 2
    assert {d.updated_at for d in docs} == {indexer.run_started_at}
    assert indexer.run_started_at.tzinfo is timezone.utc
    # The stamp is not part of the identity: the same chunk keeps its ID and content hash across runs.
    plain = _indexer().build_documents([_row()])[0][0]
    assert docs[0].document_id == plain.document_id and docs[0].content_hash == plain.content_hash


def test_a_run_id_comes_from_the_argument_then_the_environment_then_a_fresh_one(monkeypatch) -> None:
    assert _indexer(sweep=True, run_id="a").run_id == "a"
    monkeypatch.setenv("INGEST_RUN_ID", "from-env")
    assert _indexer(sweep=True).run_id == "from-env"
    monkeypatch.delenv("INGEST_RUN_ID")
    first, second = _indexer(sweep=True).run_id, _indexer(sweep=True).run_id
    assert first != second and len(first) == 32


@pytest.mark.parametrize("bad", ["", " ", "has space", "a/b", "x" * 65, "-lead"])
def test_an_unusable_run_id_fails_at_start(bad) -> None:
    with pytest.raises(ValueError):
        _indexer(sweep=True, run_id=bad or " ")


def test_finalize_finds_stale_chunks_for_this_tenant_and_run_then_deletes_them_with_a_tenant_scope() -> None:
    provider = SweepProvider(stale=("a", "b", "c"), files=("guide.pdf", "faq.pdf"))
    indexer = _indexer(provider, sweep=True, run_id="job-7")
    report = indexer.finalize()

    (find,) = provider.find_calls
    assert find["tenant_id"] == "acme" and find["provider_name"] == "ray-ingest"
    assert find["run_id"] == "job-7" and find["run_started_at"] == indexer.run_started_at
    assert find["index"] == "chunks-test" and find["max_documents"] == 10_000
    ((ids, scope, index),) = provider.delete_calls
    assert ids == ["a", "b", "c"] and index == "chunks-test"
    assert scope.tenant_id == "acme" and scope.acl_tokens == ("tenant:acme",)
    assert (report.files, report.deleted) == (2, 3)
    assert provider.closed


def test_nothing_stale_means_no_delete_call() -> None:
    provider = SweepProvider(stale=(), files=("guide.pdf",))
    report = _indexer(provider, sweep=True, run_id="r").finalize()
    assert provider.delete_calls == [] and (report.files, report.deleted) == (1, 0)


def test_a_refusal_from_the_provider_fails_the_job_and_deletes_nothing() -> None:
    from app.search.sweep import SweepRefused

    provider = SweepProvider(find_error=SweepRefused("too many"))
    with pytest.raises(SweepRefused):
        _indexer(provider, sweep=True, run_id="r").finalize()
    assert provider.delete_calls == [] and provider.closed


def test_a_failed_delete_fails_the_job_naming_ids_and_codes() -> None:
    from pipelines.ingestion.indexing.opensearch import IndexerError

    provider = SweepProvider(stale=("a", "b"), failed=("b",))
    with pytest.raises(IndexerError, match=r"1 stale chunks could not be deleted \(b=bulk_delete\)"):
        _indexer(provider, sweep=True, run_id="r").finalize()


def test_the_delete_cap_is_configurable_and_validated(monkeypatch) -> None:
    assert _indexer(sweep=True, run_id="r", max_sweep_documents=5).max_sweep_documents == 5
    monkeypatch.setenv("INGEST_OPENSEARCH_SWEEP_MAX_DELETE", "250")
    assert _indexer(sweep=True, run_id="r").max_sweep_documents == 250
    monkeypatch.setenv("INGEST_OPENSEARCH_SWEEP_MAX_DELETE", "-3")
    with pytest.raises(ValueError, match="positive"):
        _indexer(sweep=True, run_id="r")
    monkeypatch.setenv("INGEST_OPENSEARCH_SWEEP_MAX_DELETE", "lots")
    with pytest.raises(ValueError):
        _indexer(sweep=True, run_id="r")


def test_the_indexer_still_pickles_with_the_sweep_on() -> None:
    from pipelines.ingestion.indexing.opensearch import OpenSearchIndexer

    indexer = OpenSearchIndexer("acme", index="i", dimensions=DIM, sweep=True, run_id="job-7", max_sweep_documents=9)
    restored = pickle.loads(pickle.dumps(indexer))
    assert (restored.run_id, restored.run_started_at, restored.max_sweep_documents) == (
        "job-7",
        indexer.run_started_at,
        9,
    )


def test_a_sweep_flag_without_an_opensearch_sink_is_a_start_up_error() -> None:
    from pipelines.ingestion.indexing.sinks import build_vector_sinks

    with pytest.raises(ValueError, match="INGEST_OPENSEARCH_SWEEP is on but opensearch is not"):
        build_vector_sinks({"INGEST_OPENSEARCH_SWEEP": "true", "INGEST_VECTOR_SINKS": "qdrant"})


def test_finalize_sinks_runs_only_sinks_that_have_a_finalize() -> None:
    from pipelines.ingestion.indexing.sinks import finalize_sinks

    class Plain:
        def write(self, batch):
            pass

    class Sweeper:
        def finalize(self):
            return "report"

    class Quiet:
        def finalize(self):
            return None

    assert finalize_sinks([Plain(), Sweeper(), Quiet()]) == ["report"]
