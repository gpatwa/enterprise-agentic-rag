# services/api/tests/test_support_data_core.py
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


def _zendesk_raw(ticket_id: int = 42) -> dict:
    return {
        "id": ticket_id,
        "subject": "API timeout on export",
        "description": "Customer reports exports timing out after 30 seconds.",
        "status": "open",
        "priority": "high",
        "type": "incident",
        "requester_id": 1001,
        "assignee_id": 2002,
        "organization_id": 3003,
        "tags": ["api", "export"],
        "via": {"channel": "web"},
        "custom_fields": [{"id": 10, "value": "enterprise"}],
        "created_at": "2026-05-29T12:00:00Z",
        "updated_at": "2026-05-30T12:00:00Z",
        "url": "https://example.zendesk.com/api/v2/tickets/42.json",
    }


def _intercom_raw(conversation_id: str = "conv_1") -> dict:
    return {
        "id": conversation_id,
        "state": "open",
        "source": {
            "type": "conversation",
            "subject": "Billing plan question",
            "body": "Can I switch plans mid-cycle?",
            "author": {
                "id": "contact_1",
                "email": "buyer@example.com",
                "name": "Buyer One",
                "type": "user",
            },
        },
        "tags": {"tags": [{"name": "billing"}]},
        "created_at": 1780065600,
        "updated_at": 1780152000,
    }


def _zendesk_comment_raw(comment_id: int = 501) -> dict:
    return {
        "id": comment_id,
        "author_id": 1001,
        "body": "Restarting the export worker resolved the timeout.",
        "plain_body": "Restarting the export worker resolved the timeout.",
        "public": True,
        "created_at": "2026-05-30T13:00:00Z",
    }


def _zendesk_article_raw(article_id: int = 701) -> dict:
    return {
        "id": article_id,
        "title": "Troubleshooting export timeouts",
        "body": "Check worker health, retry the export, and escalate if the queue is saturated.",
        "locale": "en-us",
        "html_url": "https://example.zendesk.com/hc/articles/701",
        "updated_at": "2026-05-30T14:00:00Z",
    }


async def _session():
    import app.support.models  # noqa: F401
    from app.memory.postgres import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session


class TestSupportNormalizers:
    def test_zendesk_ticket_normalizes_to_internal_shape(self):
        from app.support.normalizers import normalize_zendesk_ticket

        ticket = normalize_zendesk_ticket(_zendesk_raw())
        assert ticket.provider == "zendesk"
        assert ticket.external_id == "42"
        assert ticket.subject == "API timeout on export"
        assert ticket.status == "open"
        assert ticket.channel == "web"
        assert ticket.tags == ["api", "export"]
        assert ticket.customer is not None
        assert ticket.customer.external_id == "1001"

    def test_intercom_conversation_normalizes_to_internal_shape(self):
        from app.support.normalizers import normalize_intercom_conversation

        ticket = normalize_intercom_conversation(_intercom_raw())
        assert ticket.provider == "intercom"
        assert ticket.external_id == "conv_1"
        assert ticket.subject == "Billing plan question"
        assert ticket.status == "open"
        assert ticket.tags == ["billing"]
        assert ticket.customer is not None
        assert ticket.customer.email == "buyer@example.com"

    def test_zendesk_comment_and_article_normalize_to_internal_shape(self):
        from app.support.normalizers import normalize_zendesk_article, normalize_zendesk_comment

        comment = normalize_zendesk_comment(_zendesk_comment_raw(), ticket_external_id="42")
        article = normalize_zendesk_article(_zendesk_article_raw())

        assert comment.provider == "zendesk"
        assert comment.ticket_external_id == "42"
        assert comment.external_id == "501"
        assert comment.body_text == "Restarting the export worker resolved the timeout."
        assert comment.is_public is True
        assert article.provider == "zendesk"
        assert article.external_id == "701"
        assert article.title == "Troubleshooting export timeouts"


class TestSupportDataStore:
    @pytest.mark.asyncio
    async def test_ticket_upsert_is_idempotent_and_tenant_scoped(self):
        from app.support.models import SupportTicket
        from app.support.normalizers import normalize_zendesk_ticket
        from app.support.store import support_data_store

        engine, Session = await _session()
        try:
            async with Session() as session:
                ticket = normalize_zendesk_ticket(_zendesk_raw())
                created = await support_data_store.upsert_ticket(
                    session, tenant_id="tenant-a", ticket=ticket
                )
                updated = await support_data_store.upsert_ticket(
                    session, tenant_id="tenant-a", ticket=ticket
                )
                await session.commit()

                assert created is True
                assert updated is False
                count = await session.scalar(select(func.count(SupportTicket.id)))
                assert count == 1

                other_tenant_ticket = normalize_zendesk_ticket(_zendesk_raw())
                created_other = await support_data_store.upsert_ticket(
                    session, tenant_id="tenant-b", ticket=other_tenant_ticket
                )
                await session.commit()
                assert created_other is True
                count = await session.scalar(select(func.count(SupportTicket.id)))
                assert count == 2
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_comment_and_article_upserts_are_idempotent_and_tenant_scoped(self):
        from app.support.models import SupportArticle, SupportTicketComment
        from app.support.normalizers import normalize_zendesk_article, normalize_zendesk_comment
        from app.support.store import support_data_store

        engine, Session = await _session()
        try:
            async with Session() as session:
                comment = normalize_zendesk_comment(_zendesk_comment_raw(), ticket_external_id="42")
                article = normalize_zendesk_article(_zendesk_article_raw())

                created_comment = await support_data_store.upsert_comment(
                    session, tenant_id="tenant-a", comment=comment
                )
                updated_comment = await support_data_store.upsert_comment(
                    session, tenant_id="tenant-a", comment=comment
                )
                created_article = await support_data_store.upsert_article(
                    session, tenant_id="tenant-a", article=article
                )
                updated_article = await support_data_store.upsert_article(
                    session, tenant_id="tenant-a", article=article
                )
                await session.commit()

                assert created_comment is True
                assert updated_comment is False
                assert created_article is True
                assert updated_article is False
                comment_count = await session.scalar(select(func.count(SupportTicketComment.id)))
                article_count = await session.scalar(select(func.count(SupportArticle.id)))
                assert comment_count == 1
                assert article_count == 1
        finally:
            await engine.dispose()


class TestSupportSyncRunner:
    @pytest.mark.asyncio
    async def test_sync_persists_tickets_and_sync_run(self, monkeypatch):
        import app.support.sync as sync_mod
        from app.support.models import SupportArticle, SupportSyncRun, SupportTicket, SupportTicketComment
        from app.support.sync import support_sync_runner
        from app.support_integrations.types import (
            SupportArticlePreview,
            SupportCommentPreview,
            SupportTicketPreview,
        )

        engine, Session = await _session()
        fake_manager = type(
            "FakeSupportIntegrationManager",
            (),
            {
                "list_ticket_previews": AsyncMock(
                    return_value=[
                        SupportTicketPreview(
                            id="42",
                            subject="API timeout on export",
                            status="open",
                            requester="1001",
                            updated_at="2026-05-30T12:00:00Z",
                            url="https://example.zendesk.com/api/v2/tickets/42.json",
                            raw=_zendesk_raw(),
                        )
                    ]
                ),
                "list_ticket_comments": AsyncMock(
                    return_value=[
                        SupportCommentPreview(
                            id="501",
                            ticket_id="42",
                            author="1001",
                            created_at="2026-05-30T13:00:00Z",
                            is_public=True,
                            raw=_zendesk_comment_raw(),
                        )
                    ]
                ),
                "list_article_previews": AsyncMock(
                    return_value=[
                        SupportArticlePreview(
                            id="701",
                            title="Troubleshooting export timeouts",
                            updated_at="2026-05-30T14:00:00Z",
                            url="https://example.zendesk.com/hc/articles/701",
                            raw=_zendesk_article_raw(),
                        )
                    ]
                ),
            },
        )()
        monkeypatch.setattr(sync_mod, "support_integration_manager", fake_manager)

        try:
            async with Session() as session:
                run = await support_sync_runner.sync_provider(
                    session,
                    tenant_id="tenant-a",
                    provider="zendesk",
                    requested_by="admin-user",
                    limit=10,
                )

                assert run["status"] == "succeeded"
                assert run["records_seen"] == 1
                assert run["records_upserted"] == 1
                assert run["records_skipped"] == 0
                assert run["metadata"]["comments_seen"] == 1
                assert run["metadata"]["comments_upserted"] == 1
                assert run["metadata"]["articles_seen"] == 1
                assert run["metadata"]["articles_upserted"] == 1

                ticket_count = await session.scalar(select(func.count(SupportTicket.id)))
                comment_count = await session.scalar(select(func.count(SupportTicketComment.id)))
                article_count = await session.scalar(select(func.count(SupportArticle.id)))
                sync_count = await session.scalar(select(func.count(SupportSyncRun.id)))
                assert ticket_count == 1
                assert comment_count == 1
                assert article_count == 1
                assert sync_count == 1
        finally:
            await engine.dispose()
