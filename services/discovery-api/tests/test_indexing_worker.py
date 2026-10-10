from app.indexing.worker import BulkIndexRequest, FakeBulkIndexProvider, IndexingWorker


def record(checkpoint: int, document_id: str = "tenant-a:experience-1") -> BulkIndexRequest:
    return BulkIndexRequest(
        checkpoint=checkpoint,
        tenant_id="tenant-a",
        document_id=document_id,
        document={"tenant_id": "tenant-a", "exposure_key": document_id, "title": "Demo"},
        document_version="catalog-v1",
    )


def test_worker_upserts_idempotently_and_advances_checkpoint() -> None:
    provider = FakeBulkIndexProvider()
    worker = IndexingWorker(provider, batch_size=2)

    first = worker.run((record(1), record(2, "tenant-a:experience-2")))
    second = worker.run((record(3, "tenant-a:experience-3"),), checkpoint=first.checkpoint)

    assert first.accepted == 2
    assert first.checkpoint == 2
    assert second.checkpoint == 3
    assert len(provider.documents) == 3
    assert first.external_index_updated is False


def test_transient_failures_are_retried_with_bounded_attempts() -> None:
    provider = FakeBulkIndexProvider(transient_attempts={"tenant-a:experience-1": 2})
    evidence = IndexingWorker(provider, max_attempts=3).run((record(1),))

    assert evidence.accepted == 1
    assert evidence.attempts == 3
    assert provider.attempts["tenant-a:experience-1"] == 3


def test_poison_record_is_quarantined_and_checkpoint_stops_before_it() -> None:
    provider = FakeBulkIndexProvider(permanent_failures={"tenant-a:experience-2"})
    worker = IndexingWorker(provider, batch_size=3, max_attempts=2)
    evidence = worker.run((record(1), record(2, "tenant-a:experience-2"), record(3, "tenant-a:experience-3")))

    assert evidence.accepted == 2
    assert evidence.quarantined == 1
    assert evidence.checkpoint == 1
    assert evidence.failures[0].document_digest != "tenant-a:experience-2"
    assert evidence.failures[0].attempts == 1


def test_worker_rejects_unbounded_or_unordered_input() -> None:
    provider = FakeBulkIndexProvider()
    worker = IndexingWorker(provider)

    try:
        worker.run((record(2), record(1, "tenant-a:experience-2")))
    except ValueError as exc:
        assert "ordered" in str(exc)
    else:
        raise AssertionError("unordered input must be rejected")
