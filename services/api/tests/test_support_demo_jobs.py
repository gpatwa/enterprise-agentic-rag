from __future__ import annotations

import os
from datetime import datetime, timedelta
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
        from app.support.models import SupportJob

        engine, Session = await _session()
        manager = SupportJobManager()
        try:
            async with Session() as session:
                job = await manager.start_sync_index_job(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                    providers=["Zendesk", "zendesk"],
                    limit=500,
                    seed_demo=True,
                )

                assert job["status"] == "queued"
                assert job["providers"] == ["zendesk"]
                assert job["limit"] == 200
                assert job["seed_demo"] is True
                assert job["attempt_count"] == 0

                tenant_jobs = await manager.list_jobs(session, tenant_id="tenant-a")
                other_tenant_jobs = await manager.list_jobs(session, tenant_id="tenant-b")
                persisted = await session.get(SupportJob, job["id"])

                assert [item["id"] for item in tenant_jobs] == [job["id"]]
                assert other_tenant_jobs == []
                assert persisted is not None
                assert persisted.status == "queued"
                assert persisted.max_attempts >= 1

                with pytest.raises(ValueError):
                    await manager.start_sync_index_job(
                        session,
                        tenant_id="tenant-a",
                        requested_by="alice",
                        providers=["salesforce"],
                    )
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_job_controls_cancel_retry_summary_and_stale_dead_letter(self):
        from app.support.jobs import SupportJobManager
        from app.support.models import SupportJob

        engine, Session = await _session()
        manager = SupportJobManager()
        try:
            async with Session() as session:
                job = await manager.start_sync_index_job(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                    providers=["zendesk"],
                    limit=10,
                )

                canceled = await manager.cancel_job(
                    session,
                    tenant_id="tenant-a",
                    job_id=job["id"],
                )
                retry = await manager.retry_job(
                    session,
                    tenant_id="tenant-a",
                    job_id=job["id"],
                    requested_by="bob",
                )

                assert canceled is not None
                assert canceled["status"] == "canceled"
                assert canceled["cancel_requested"] is True
                assert canceled["canceled_at"] is not None
                assert retry is not None
                assert retry["status"] == "queued"
                assert retry["retry_of_job_id"] == job["id"]

                with pytest.raises(ValueError):
                    await manager.retry_job(
                        session,
                        tenant_id="tenant-a",
                        job_id=retry["id"],
                        requested_by="bob",
                    )

                claimed = await manager.claim_next_job(
                    session,
                    worker_id="test-worker",
                    stale_after_seconds=60,
                )
                assert claimed is not None

                row = await session.get(SupportJob, claimed["id"])
                assert row is not None
                row.locked_at = datetime.utcnow() - timedelta(seconds=120)
                row.attempt_count = row.max_attempts
                await session.commit()

                recovered = await manager.recover_stale_running_jobs(
                    session,
                    stale_after_seconds=60,
                )
                await session.commit()
                dead_lettered = await manager.get_job(
                    session,
                    tenant_id="tenant-a",
                    job_id=claimed["id"],
                )
                summary = await manager.job_summary(
                    session,
                    tenant_id="tenant-a",
                    stale_after_seconds=60,
                )

                assert recovered == 1
                assert dead_lettered is not None
                assert dead_lettered["status"] == "failed"
                assert dead_lettered["current_step"] == "dead_lettered_after_stale_lock"
                assert summary["counts"]["canceled"] == 1
                assert summary["dead_letter_count"] == 1
                assert summary["stale_running_count"] == 0
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_fail_job_requeues_until_attempts_are_exhausted(self):
        from app.support.jobs import SupportJobManager
        from app.support.models import SupportJob

        engine, Session = await _session()
        manager = SupportJobManager()
        try:
            async with Session() as session:
                job = await manager.start_sync_index_job(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                    providers=["zendesk"],
                )
                claimed = await manager.claim_next_job(
                    session,
                    worker_id="test-worker",
                    stale_after_seconds=60,
                )

                assert claimed is not None
                assert claimed["id"] == job["id"]

                retried = await manager.fail_job(
                    session,
                    job_id=job["id"],
                    message="transient worker crash",
                    result={"errors": []},
                )
                assert retried is not None
                assert retried["status"] == "queued"
                assert retried["current_step"] == "retry_scheduled"
                assert retried["next_run_at"] is not None

                not_ready = await manager.claim_next_job(
                    session,
                    worker_id="test-worker",
                    stale_after_seconds=60,
                )
                assert not_ready is None

                row = await session.get(SupportJob, job["id"])
                assert row is not None
                row.status = "running"
                row.attempt_count = row.max_attempts
                await session.commit()

                terminal = await manager.fail_job(
                    session,
                    job_id=job["id"],
                    message="still broken",
                    result={"errors": []},
                )

                assert terminal is not None
                assert terminal["status"] == "failed"
                assert terminal["current_step"] == "failed"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_worker_processes_persisted_job_status(self, monkeypatch):
        import app.support.jobs as jobs_mod
        from app.support.jobs import SupportJobManager, SupportJobWorker

        class FakeSyncRunner:
            async def sync_provider(self, *args, **kwargs):
                return {
                    "id": 123,
                    "provider": kwargs["provider"],
                    "status": "succeeded",
                    "records_seen": 0,
                    "records_upserted": 0,
                    "records_skipped": 0,
                    "metadata": {},
                }

        class FakeIndexer:
            async def index_tickets(self, *args, **kwargs):
                return {
                    "tenant_id": kwargs["tenant_id"],
                    "provider": kwargs["provider"],
                    "tickets_seen": 0,
                    "tickets_total": 0,
                    "comments_seen": 0,
                    "comments_total": 0,
                    "articles_seen": 0,
                    "articles_total": 0,
                    "indexed": 0,
                    "skipped": 0,
                    "chunks": 0,
                    "errors": [],
                }

        engine, Session = await _session()
        manager = SupportJobManager()
        worker = SupportJobWorker(manager, worker_id="test-worker")
        worker.configure(Session, poll_seconds=0.1, stale_after_seconds=60)
        monkeypatch.setattr(jobs_mod, "support_sync_runner", FakeSyncRunner())
        monkeypatch.setattr(jobs_mod, "support_indexer", FakeIndexer())

        try:
            async with Session() as session:
                job = await manager.start_sync_index_job(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                    providers=["zendesk"],
                    limit=10,
                )

            processed = await worker.process_next_job()

            async with Session() as session:
                persisted = await manager.get_job(session, tenant_id="tenant-a", job_id=job["id"])

            assert processed is True
            assert persisted is not None
            assert persisted["status"] == "succeeded"
            assert persisted["current_step"] == "finished"
            assert persisted["attempt_count"] == 1
            assert persisted["result"]["sync_runs"][0]["provider"] == "zendesk"
            assert persisted["result"]["index"]["indexed"] == 0
        finally:
            await engine.dispose()
