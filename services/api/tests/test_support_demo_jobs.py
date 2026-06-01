from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


def _ctx(role: str = "admin", tenant_id: str = "tenant-a", user_id: str = "alice"):
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id=tenant_id,
        user_id=user_id,
        role=role,
        permissions=[],
    )


async def _session():
    import app.support.models  # noqa: F401
    from app.memory.postgres import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, Session


class TestSupportDemoData:
    @pytest.mark.asyncio
    async def test_seed_demo_data_is_idempotent_and_records_sync_runs(self):
        from app.support.demo import seed_demo_data
        from app.support.models import (
            SupportArticle,
            SupportCustomer,
            SupportSyncRun,
            SupportTicket,
            SupportTicketComment,
        )

        engine, Session = await _session()
        try:
            async with Session() as session:
                first = await seed_demo_data(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                )
                second = await seed_demo_data(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                )

                assert first["provider"] == "zendesk"
                assert first["customers_created"] == 3
                assert first["tickets_created"] == 3
                assert first["comments_created"] == 4
                assert first["articles_created"] == 3
                assert second["customers_created"] == 0
                assert second["tickets_created"] == 0
                assert second["comments_created"] == 0
                assert second["articles_created"] == 0

                customer_count = await session.scalar(select(func.count(SupportCustomer.id)))
                ticket_count = await session.scalar(select(func.count(SupportTicket.id)))
                comment_count = await session.scalar(select(func.count(SupportTicketComment.id)))
                article_count = await session.scalar(select(func.count(SupportArticle.id)))
                sync_count = await session.scalar(select(func.count(SupportSyncRun.id)))
                latest_run = await session.scalar(
                    select(SupportSyncRun).order_by(SupportSyncRun.started_at.desc()).limit(1)
                )

                assert customer_count == 3
                assert ticket_count == 3
                assert comment_count == 4
                assert article_count == 3
                assert sync_count == 2
                assert latest_run is not None
                assert latest_run.metadata_["demo"] is True
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_seed_route_returns_demo_data_when_index_is_unavailable(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes
        from app.support.indexer import SupportIndexError

        class FailingIndexer:
            async def index_tickets(self, *args, **kwargs):
                raise SupportIndexError("support index clients are not configured")

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)
        monkeypatch.setattr(routes, "support_indexer", FailingIndexer())
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())

        try:
            body = await routes.seed_support_demo(_ctx())

            assert body["seed"]["tickets_created"] == 3
            assert body["index_status"] == "failed"
            assert body["index"] is None
            assert "support index clients" in body["index_error"]
        finally:
            await engine.dispose()


class TestSupportJobManager:
    @pytest.mark.asyncio
    async def test_sync_index_job_creation_is_tenant_scoped_and_validates_providers(self):
        from app.support.jobs import SupportJobManager

        manager = SupportJobManager()
        job = await manager.start_sync_index_job(
            tenant_id="tenant-a",
            requested_by="alice",
            providers=["Zendesk", "zendesk"],
            limit=500,
            seed_demo=True,
            start_background=False,
        )

        assert job["status"] == "queued"
        assert job["providers"] == ["zendesk"]
        assert job["limit"] == 200
        assert job["seed_demo"] is True

        tenant_jobs = await manager.list_jobs(tenant_id="tenant-a")
        other_tenant_jobs = await manager.list_jobs(tenant_id="tenant-b")
        assert [item["id"] for item in tenant_jobs] == [job["id"]]
        assert other_tenant_jobs == []

        with pytest.raises(ValueError):
            await manager.start_sync_index_job(
                tenant_id="tenant-a",
                requested_by="alice",
                providers=["salesforce"],
                start_background=False,
            )
