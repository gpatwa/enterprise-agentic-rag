from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def _database():
    import app.support.models  # noqa: F401
    from app.memory.postgres import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


def _ticket(tenant_id: str = "tenant-a"):
    from app.support.models import SupportTicket

    now = datetime(2026, 8, 22, 12, 0, 0)
    return SupportTicket(
        tenant_id=tenant_id,
        provider="zendesk",
        external_id="42",
        subject="Export timeout",
        description="The export timed out.",
        status="open",
        priority="high",
        category="incident",
        channel="web",
        tags=["export"],
        raw={},
        created_at=now,
        updated_at=now,
        first_seen_at=now,
        last_synced_at=now,
        updated_at_external=now,
    )


@pytest.mark.asyncio
async def test_backfill_is_checkpointed_idempotent_and_supports_dry_run():
    from app.search.backfill import support_search_backfill
    from app.support.models import SupportSearchCheckpoint, SupportSearchOutboxEvent

    engine, factory = await _database()
    try:
        async with factory() as session:
            session.add(_ticket())
            await session.commit()
            report = await support_search_backfill.run(
                session,
                tenant_id="tenant-a",
                provider="zendesk",
                batch_size=1,
            )
            assert report.records_seen == 1
            assert report.events_queued == 1
            assert report.checkpoints_advanced == 1
            assert await session.scalar(select(SupportSearchOutboxEvent.id))
            checkpoint = await session.scalar(
                select(SupportSearchCheckpoint)
            )
            assert checkpoint.cursor == "1"

            rerun = await support_search_backfill.run(
                session,
                tenant_id="tenant-a",
                provider="zendesk",
                batch_size=1,
            )
            assert rerun.records_seen == 0

            dry_run = await support_search_backfill.run(
                session,
                tenant_id="tenant-b",
                provider="zendesk",
                dry_run=True,
            )
            assert dry_run.records_seen == 0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_event_processor_applies_canonical_upsert_and_delete():
    from app.search.indexing import SupportSearchEventProcessor
    from app.search.models import BulkWriteResult
    from app.search.support_mapper import map_ticket
    from app.support.models import SupportSearchOutboxEvent

    engine, factory = await _database()
    try:
        async with factory() as session:
            ticket = _ticket()
            session.add(ticket)
            await session.flush()
            document = map_ticket(ticket)
            event = SupportSearchOutboxEvent(
                idempotency_key="event-1",
                tenant_id="tenant-a",
                provider="zendesk",
                event_type="upsert",
                source_type="ticket",
                source_id="42",
                payload={"document": document.model_dump(mode="json")},
            )
            session.add(event)
            await session.commit()

        class Provider:
            def __init__(self):
                self.upserts = []
                self.deletes = []

            async def upsert(self, documents):
                self.upserts.extend(documents)
                return BulkWriteResult(attempted=1, succeeded=1, failed=0)

            async def delete(self, document_ids, *, scope):
                self.deletes.append((document_ids, scope))
                return BulkWriteResult(attempted=1, succeeded=1, failed=0)

        provider = Provider()
        processor = SupportSearchEventProcessor(provider, factory)
        async with factory() as session:
            stored = await session.get(SupportSearchOutboxEvent, event.id)
        await processor(stored)
        assert provider.upserts[0].document_id == document.document_id

        stored.event_type = "delete"
        await processor(stored)
        assert provider.deletes[0][1].tenant_id == "tenant-a"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reconcile_reports_missing_extra_stale_acl_and_version_drift():
    from app.search.reconcile import SearchReconciler
    from app.search.support_mapper import map_ticket

    engine, factory = await _database()
    try:
        async with factory() as session:
            ticket = _ticket()
            session.add(ticket)
            await session.flush()
            document = map_ticket(ticket)
            raw = document.model_dump(mode="json")
            raw["content_version"] = "sha256:" + "0" * 64
            raw["permission_version"] = "wrong"
            raw["schema_version"] = "old-schema"
            raw["document_id"] = document.document_id
            report = await SearchReconciler().reconcile(
                session,
                tenant_id="tenant-a",
                provider=object(),
                source_provider="zendesk",
                index_documents=[raw, {"document_id": "extra", "tenant_id": "tenant-a"}],
            )
            assert report.stale == (document.document_id,)
            assert report.acl_mismatched == (document.document_id,)
            assert report.version_mismatched == (document.document_id,)
            assert report.extra == ("extra",)
            assert report.clean is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reindex_swaps_alias_only_after_clean_report():
    from app.search.models import BulkWriteResult
    from app.search.reindex import SearchReindexCoordinator

    engine, factory = await _database()
    try:
        async with factory() as session:
            session.add(_ticket())
            await session.commit()

            class Provider:
                def __init__(self):
                    self.documents = {}
                    self.ensured = []
                    self.activated = []

                async def ensure_index(self, spec):
                    self.ensured.append(spec)

                async def upsert(self, documents, *, index):
                    for document in documents:
                        self.documents[document.document_id] = {
                            **document.model_dump(mode="json"),
                            "document_id": document.document_id,
                        }
                    return BulkWriteResult(
                        attempted=len(documents),
                        succeeded=len(documents),
                        failed=0,
                    )

                async def list_documents(self, *, index):
                    return list(self.documents.values())

                async def activate_alias(self, alias, index_name):
                    self.activated.append((alias, index_name))

            provider = Provider()
            result = await SearchReindexCoordinator().run(
                session,
                tenant_id="tenant-a",
                provider_name="zendesk",
                provider=provider,
                alias="support-search",
                generation="support-search-v2",
            )
            assert result.swapped is True
            assert result.report.clean is True
            assert provider.activated == [("support-search", "support-search-v2")]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_reindex_does_not_swap_a_generation_with_missing_documents():
    from app.search.models import BulkWriteResult
    from app.search.reindex import SearchReindexCoordinator

    engine, factory = await _database()
    try:
        async with factory() as session:
            session.add(_ticket())
            await session.commit()

            class Provider:
                async def ensure_index(self, spec):
                    pass

                async def upsert(self, documents, *, index):
                    return BulkWriteResult(
                        attempted=len(documents),
                        succeeded=len(documents),
                        failed=0,
                    )

                async def list_documents(self, *, index):
                    return []

                async def activate_alias(self, alias, index_name):
                    raise AssertionError("unsafe generation must not become active")

            result = await SearchReindexCoordinator().run(
                session,
                tenant_id=None,
                provider_name="zendesk",
                provider=Provider(),
                alias="shared-support-search",
                generation="shared-support-search-v3",
            )
            assert result.swapped is False
            assert result.report.missing_count == 1
    finally:
        await engine.dispose()


def test_search_worker_is_a_separate_deployable():
    entrypoint = Path(__file__).parents[1] / "search_worker.py"
    helm_template = (
        Path(__file__).parents[2]
        / ".."
        / "deploy"
        / "helm"
        / "api"
        / "templates"
        / "search-worker-deployment.yaml"
    )
    assert entrypoint.exists()
    assert "SearchIndexWorker" in entrypoint.read_text()
    assert helm_template.exists()
    assert ".Values.searchWorker.command" in helm_template.read_text()
