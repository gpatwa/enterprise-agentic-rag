# services/api/tests/test_support_indexing.py
from __future__ import annotations

import os
from datetime import datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


async def _session():
    import app.support.models  # noqa: F401
    from app.memory.postgres import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session


def _ticket(**overrides):
    from app.support.models import SupportTicket

    values = {
        "tenant_id": "tenant-a",
        "provider": "zendesk",
        "external_id": "42",
        "subject": "API timeout on export",
        "description": "Customer reports exports timing out after 30 seconds.",
        "status": "open",
        "priority": "high",
        "category": "incident",
        "channel": "web",
        "requester_external_id": "1001",
        "assignee_external_id": "2002",
        "organization_external_id": "3003",
        "tags": ["api", "export"],
        "custom_fields": {"plan": "enterprise"},
        "raw": {"id": 42},
        "source_url": "https://example.zendesk.com/tickets/42",
        "created_at_external": datetime(2026, 5, 29, 12, 0, 0),
        "updated_at_external": datetime(2026, 5, 30, 12, 0, 0),
        "first_seen_at": datetime(2026, 5, 30, 12, 0, 0),
        "last_synced_at": datetime(2026, 5, 30, 12, 0, 0),
        "created_at": datetime(2026, 5, 30, 12, 0, 0),
        "updated_at": datetime(2026, 5, 30, 12, 0, 0),
    }
    values.update(overrides)
    return SupportTicket(**values)


def _comment(**overrides):
    from app.support.models import SupportTicketComment

    values = {
        "tenant_id": "tenant-a",
        "provider": "zendesk",
        "ticket_external_id": "42",
        "external_id": "501",
        "author_external_id": "1001",
        "body_text": "Restarting the export worker resolved the timeout.",
        "body_html": None,
        "is_public": True,
        "raw": {"id": 501},
        "created_at_external": datetime(2026, 5, 30, 13, 0, 0),
        "created_at": datetime(2026, 5, 30, 13, 0, 0),
    }
    values.update(overrides)
    return SupportTicketComment(**values)


def _article(**overrides):
    from app.support.models import SupportArticle

    values = {
        "tenant_id": "tenant-a",
        "provider": "zendesk",
        "external_id": "701",
        "title": "Troubleshooting export timeouts",
        "body_text": "Check worker health and retry the export.",
        "body_html": None,
        "locale": "en-us",
        "source_url": "https://example.zendesk.com/hc/articles/701",
        "raw": {"id": 701},
        "updated_at_external": datetime(2026, 5, 30, 14, 0, 0),
        "created_at": datetime(2026, 5, 30, 14, 0, 0),
        "updated_at": datetime(2026, 5, 30, 14, 0, 0),
    }
    values.update(overrides)
    return SupportArticle(**values)


class FakeEmbedClient:
    def __init__(self):
        self.documents: list[str] = []
        self.queries: list[str] = []

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.documents.extend(texts)
        return [[1.0, float(idx), 0.5] for idx, _ in enumerate(texts)]

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return [0.2, 0.3, 0.4]


class FakeVectorClient:
    def __init__(self):
        self.collections: list[tuple[str, int]] = []
        self.deletes: list[tuple[str, dict]] = []
        self.upserts: list[tuple[str, list[dict]]] = []
        self.searches: list[dict] = []

    async def create_collection(self, collection: str, vector_size: int) -> None:
        self.collections.append((collection, vector_size))

    async def delete_by_filter(self, collection: str, filters: dict) -> None:
        self.deletes.append((collection, filters))

    async def upsert(self, collection: str, points: list[dict]) -> None:
        self.upserts.append((collection, points))

    async def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 5,
        filters: dict | None = None,
        score_threshold: float | None = None,
    ) -> list[dict]:
        self.searches.append(
            {
                "collection": collection,
                "vector": vector,
                "limit": limit,
                "filters": filters,
                "score_threshold": score_threshold,
            }
        )
        return [
            {
                "id": "point-1",
                "score": 0.91,
                "payload": {
                    "tenant_id": "tenant-a",
                    "provider": "zendesk",
                    "source_type": "ticket",
                    "source_id": "42",
                    "title": "API timeout on export",
                    "text": "Known timeout resolution steps.",
                    "status": "open",
                    "priority": "high",
                    "tags": ["api"],
                    "source_url": "https://example.zendesk.com/tickets/42",
                    "chunk_index": 0,
                    "chunk_count": 1,
                },
            }
        ]


class FailingVectorClient(FakeVectorClient):
    async def search(self, *args, **kwargs) -> list[dict]:
        raise RuntimeError("vector unavailable")


class TestSupportIndexDocuments:
    def test_ticket_document_contains_resolution_context_and_stable_hash(self):
        from app.support.documents import ticket_to_document

        ticket = _ticket()
        document = ticket_to_document(ticket)
        same_document = ticket_to_document(ticket)

        assert document.source_type == "ticket"
        assert document.source_id == "42"
        assert "Subject: API timeout on export" in document.text
        assert "Customer issue:" in document.text
        assert document.metadata["tenant_id"] == "tenant-a"
        assert document.metadata["provider"] == "zendesk"
        assert document.metadata["tags"] == ["api", "export"]
        assert document.content_hash == same_document.content_hash

    def test_comment_and_article_documents_include_resolution_text(self):
        from app.support.documents import article_to_document, comment_to_document

        comment_doc = comment_to_document(_comment())
        article_doc = article_to_document(_article())

        assert comment_doc.source_type == "comment"
        assert comment_doc.metadata["ticket_external_id"] == "42"
        assert "Restarting the export worker" in comment_doc.text
        assert article_doc.source_type == "article"
        assert article_doc.title == "Troubleshooting export timeouts"
        assert "Check worker health" in article_doc.text

    def test_chunk_text_keeps_chunks_bounded_with_overlap(self):
        from app.support.documents import chunk_text

        text = "0123456789" * 80
        chunks = chunk_text(text, chunk_chars=200, overlap_chars=25)

        assert len(chunks) > 1
        assert all(len(chunk) <= 200 for chunk in chunks)
        assert chunks[0][-25:] == chunks[1][:25]


class TestSupportIndexer:
    @pytest.mark.asyncio
    async def test_index_tickets_upserts_vectors_and_skips_unchanged(self):
        import app.support.indexer as indexer_mod
        from app.config import settings
        from app.support.indexer import support_indexer
        from app.support.models import SupportIndexRecord

        engine, Session = await _session()
        fake_embed = FakeEmbedClient()
        fake_vector = FakeVectorClient()
        indexer_mod.set_clients(fake_vector, fake_embed)

        try:
            async with Session() as session:
                session.add(_ticket())
                await session.commit()

                summary = await support_indexer.index_tickets(
                    session,
                    tenant_id="tenant-a",
                    provider="zendesk",
                    limit=10,
                )

                assert summary["indexed"] == 1
                assert summary["skipped"] == 0
                assert summary["chunks"] == 1
                assert summary["errors"] == []
                assert fake_vector.collections == [(settings.SUPPORT_INDEX_COLLECTION, 3)]
                assert fake_vector.deletes == [
                    (
                        settings.SUPPORT_INDEX_COLLECTION,
                        {
                            "tenant_id": "tenant-a",
                            "provider": "zendesk",
                            "source_type": "ticket",
                            "source_id": "42",
                        },
                    )
                ]
                assert len(fake_vector.upserts) == 1
                point = fake_vector.upserts[0][1][0]
                assert point["payload"]["tenant_id"] == "tenant-a"
                assert point["payload"]["source_type"] == "ticket"
                assert point["payload"]["source_id"] == "42"
                assert point["payload"]["text"].startswith("Provider: zendesk")

                record = await session.scalar(select(SupportIndexRecord))
                assert record is not None
                assert record.tenant_id == "tenant-a"
                assert record.content_hash == point["payload"]["content_hash"]
                assert record.chunk_count == 1

                second_summary = await support_indexer.index_tickets(
                    session,
                    tenant_id="tenant-a",
                    provider="zendesk",
                    limit=10,
                )
                assert second_summary["indexed"] == 0
                assert second_summary["skipped"] == 1
                assert len(fake_vector.upserts) == 1
        finally:
            indexer_mod.set_clients(None, None)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_index_tickets_also_indexes_comments_and_articles(self):
        import app.support.indexer as indexer_mod
        from app.support.indexer import support_indexer

        engine, Session = await _session()
        fake_embed = FakeEmbedClient()
        fake_vector = FakeVectorClient()
        indexer_mod.set_clients(fake_vector, fake_embed)

        try:
            async with Session() as session:
                session.add_all([_ticket(), _comment(), _article()])
                await session.commit()

                summary = await support_indexer.index_tickets(
                    session,
                    tenant_id="tenant-a",
                    provider="zendesk",
                    limit=10,
                )

                assert summary["tickets_seen"] == 1
                assert summary["comments_seen"] == 1
                assert summary["articles_seen"] == 1
                assert summary["indexed"] == 3
                payload_types = [
                    upsert[1][0]["payload"]["source_type"] for upsert in fake_vector.upserts
                ]
                assert payload_types == ["ticket", "comment", "article"]
        finally:
            indexer_mod.set_clients(None, None)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_always_applies_tenant_filter(self):
        import app.support.indexer as indexer_mod
        from app.config import settings
        from app.support.indexer import support_indexer

        fake_embed = FakeEmbedClient()
        fake_vector = FakeVectorClient()
        indexer_mod.set_clients(fake_vector, fake_embed)

        try:
            results = await support_indexer.search(
                tenant_id="tenant-a",
                query="exports timing out",
                provider="zendesk",
                status="open",
                limit=3,
            )

            assert fake_embed.queries == ["exports timing out"]
            assert fake_vector.searches == [
                {
                    "collection": settings.SUPPORT_INDEX_COLLECTION,
                    "vector": [0.2, 0.3, 0.4],
                    "limit": 3,
                    "filters": {"tenant_id": "tenant-a", "provider": "zendesk", "status": "open"},
                    "score_threshold": None,
                }
            ]
            assert results[0]["source_id"] == "42"
            assert results[0]["text"] == "Known timeout resolution steps."
        finally:
            indexer_mod.set_clients(None, None)

    @pytest.mark.asyncio
    async def test_search_fuses_vector_and_lexical_results_when_session_is_available(self):
        import app.support.indexer as indexer_mod
        from app.support.indexer import support_indexer

        engine, Session = await _session()
        fake_embed = FakeEmbedClient()
        fake_vector = FakeVectorClient()
        indexer_mod.set_clients(fake_vector, fake_embed)

        try:
            async with Session() as session:
                session.add(_ticket(status="open"))
                await session.commit()

                results = await support_indexer.search(
                    tenant_id="tenant-a",
                    query="API timeout on export",
                    provider="zendesk",
                    status="open",
                    limit=3,
                    session=session,
                )

                assert results[0]["source_id"] == "42"
                assert results[0]["retrieval_source"] == "hybrid"
                assert results[0]["vector_score"] == 0.91
                assert results[0]["lexical_score"] > 0
                assert results[0]["fusion_score"] > 0
        finally:
            indexer_mod.set_clients(None, None)
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_search_can_fall_back_to_lexical_when_vector_is_unavailable(self):
        import app.support.indexer as indexer_mod
        from app.support.indexer import support_indexer

        engine, Session = await _session()
        fake_embed = FakeEmbedClient()
        fake_vector = FailingVectorClient()
        indexer_mod.set_clients(fake_vector, fake_embed)

        try:
            async with Session() as session:
                session.add(_ticket(status="open"))
                await session.commit()

                results = await support_indexer.search(
                    tenant_id="tenant-a",
                    query="API timeout on export",
                    provider="zendesk",
                    status="open",
                    limit=3,
                    session=session,
                )

                assert results[0]["source_id"] == "42"
                assert results[0]["retrieval_source"] == "lexical"
                assert results[0]["lexical_score"] > 0
        finally:
            indexer_mod.set_clients(None, None)
            await engine.dispose()
