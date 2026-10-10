from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


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
                assert first["tickets_created"] == 6
                assert first["comments_created"] == 7
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
                assert ticket_count == 6
                assert comment_count == 7
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

            assert body["seed"]["tickets_created"] == 6
            assert body["index_status"] == "failed"
            assert body["index"] is None
            assert "support index clients" in body["index_error"]
        finally:
            await engine.dispose()


class TestSupportRepeatInsights:
    @pytest.mark.asyncio
    async def test_repeat_ticket_insights_find_seeded_demo_clusters(self):
        from app.support.demo import seed_demo_data
        from app.support.insights import repeat_ticket_insights

        engine, Session = await _session()
        try:
            async with Session() as session:
                await seed_demo_data(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                )
                result = await repeat_ticket_insights(
                    session,
                    tenant_id="tenant-a",
                    provider="zendesk",
                )

                assert result["summary"]["tickets_analyzed"] == 6
                assert result["summary"]["repeat_clusters"] == 2
                assert result["summary"]["potential_deflection_count"] == 3

                clusters = {insight["title"]: insight for insight in result["insights"]}
                export = clusters["Export + Timeout"]
                billing = clusters["Billing + Invoice"]

                assert export["count"] == 3
                assert export["signals"] == ["export", "timeout"]
                assert export["deflection_candidate"] is True
                assert export["potential_deflection_count"] == 2
                assert export["statuses"]["open"] == 1
                assert "Search" not in export["related_query"]
                assert len(export["sample_tickets"]) == 3
                assert billing["count"] == 2
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_repeat_workflow_builds_playbook_gap_and_deflection(self, monkeypatch):
        import app.support.workflow as workflow_mod
        from app.support.demo import seed_demo_data

        class FakeResolver:
            def __init__(self):
                self.calls = []

            async def resolve(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "answer": "Restart the export worker and retry the export [1].",
                    "confidence": "high",
                    "citations": [
                        {
                            "label": "[1]",
                            "provider": "zendesk",
                            "source_type": "ticket",
                            "source_id": "ZD-1001",
                            "title": "Export timeout after CSV download",
                            "source_url": "https://example.zendesk.com/tickets/1001",
                            "score": 0.93,
                        }
                    ],
                    "matches": [
                        {
                            "id": "point-1",
                            "score": 0.93,
                            "provider": "zendesk",
                            "source_type": "ticket",
                            "source_id": "ZD-1001",
                            "title": "Export timeout after CSV download",
                            "text": "Restarting the export worker resolved the timeout.",
                            "status": "solved",
                            "priority": "high",
                            "tags": ["export", "timeout"],
                            "source_url": "https://example.zendesk.com/tickets/1001",
                            "chunk_index": 0,
                            "chunk_count": 1,
                        }
                    ],
                    "next_action": "suggest_agent_response",
                }

        fake_resolver = FakeResolver()
        monkeypatch.setattr(workflow_mod, "support_resolver", fake_resolver)

        engine, Session = await _session()
        try:
            async with Session() as session:
                await seed_demo_data(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                )
                result = await workflow_mod.build_repeat_resolution_workflow(
                    session,
                    tenant_id="tenant-a",
                    cluster_id="tag:export|timeout",
                    provider="zendesk",
                )

                assert result["cluster"]["title"] == "Export + Timeout"
                assert result["playbook"]["status"] == "ready_for_agent_review"
                assert result["playbook"]["verification_status"] == "evidence_ready"
                assert result["knowledge_gap"]["status"] == "missing_kb_or_macro"
                assert result["deflection_estimate"]["potential_ticket_count"] == 2
                assert result["deflection_estimate"]["confidence"] == "high"
                assert fake_resolver.calls[0]["status"] is None
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_repeat_ticket_insights_route_is_tenant_scoped(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes
        from app.support.demo import seed_demo_data

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)

        try:
            async with Session() as session:
                await seed_demo_data(
                    session,
                    tenant_id="tenant-a",
                    requested_by="alice",
                )

            body = await routes.get_repeat_ticket_insights(limit=200, min_count=2, ctx=_ctx())
            other_tenant_body = await routes.get_repeat_ticket_insights(
                limit=200,
                min_count=2,
                ctx=_ctx(tenant_id="tenant-b")
            )

            assert body["summary"]["repeat_clusters"] == 2
            assert body["insights"][0]["count"] == 3
            assert other_tenant_body["summary"]["tickets_analyzed"] == 0
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


class TestSupportActionQueue:
    @pytest.mark.asyncio
    async def test_typed_proposal_is_policy_gated_and_receipt_is_versioned(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())
        command = {
            "command_type": "send_customer_reply", "parameters": {"response": "Retry export"},
            "evidence_ids": ["ticket-1"], "idempotency_key": "proposal-1", "risk_level": "medium",
            "approval_requirement": "required", "contract_version": "support-command.v1",
            "context": {"tenant_id": "tenant-a", "principal_id": "agent-1"},
        }
        try:
            created = await routes.create_support_action_proposal(
                routes.SupportActionProposalRequest(command=command), ctx=_ctx()
            )
            action_id = created["action"]["id"]
            assert created["action"]["status"] == "generated"
            assert created["action"]["policy_status"] == "require_human_review"
            with pytest.raises(Exception) as duplicate:
                await routes.create_support_action_proposal(
                    routes.SupportActionProposalRequest(command=command), ctx=_ctx()
                )
            assert duplicate.value.status_code == 409
            with pytest.raises(Exception) as skipped:
                await routes.update_support_action_status(
                    action_id, routes.SupportActionStatusRequest(status="ready_to_execute"), ctx=_ctx()
                )
            assert skipped.value.status_code == 409
            await routes.update_support_action_status(
                action_id, routes.SupportActionStatusRequest(status="approved"), ctx=_ctx(user_id="reviewer")
            )
            await routes.update_support_action_status(
                action_id, routes.SupportActionStatusRequest(status="ready_to_execute"), ctx=_ctx(user_id="reviewer")
            )
            executed = await routes.execute_support_action(
                action_id, routes.SupportActionExecuteRequest(), ctx=_ctx(user_id="operator")
            )
            receipt = executed["action"]["execution_result"]
            assert receipt["receipt_version"] == "support-execution-receipt.v1"
            assert receipt["command_version"] == "support-command.v1"
            assert receipt["evidence_version"] == "evidence.v1"
            assert receipt["policy_version"] == "support-policy.v1"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_typed_command_lineage_is_tenant_scoped_and_idempotent(self):
        from app.support.models import SupportAction

        engine, Session = await _session()
        try:
            async with Session() as session:
                first = SupportAction(
                    id="support-action-command-a",
                    tenant_id="tenant-a",
                    created_by="alice",
                    cluster_title="Export + Timeout",
                    command_text="send customer reply",
                    command_contract_version="support-command.v1",
                    command_payload={"command_type": "send_customer_reply", "parameters": {"response": "Retry export"}},
                    policy_status="requires_review",
                    policy_reason="Customer communication requires approval",
                    evidence_ids=["ZD-1001"],
                    idempotency_key="resolution-command-1",
                )
                second = SupportAction(
                    id="support-action-command-b",
                    tenant_id="tenant-b",
                    created_by="bob",
                    cluster_title="Export + Timeout",
                    command_text="send customer reply",
                    idempotency_key="resolution-command-1",
                )
                session.add_all([first, second])
                await session.commit()

                persisted = await session.get(SupportAction, first.id)
                assert persisted is not None
                assert persisted.status == "generated"
                assert persisted.command_payload["command_type"] == "send_customer_reply"
                assert persisted.evidence_ids == ["ZD-1001"]

                duplicate = SupportAction(
                    id="support-action-command-duplicate",
                    tenant_id="tenant-a",
                    created_by="alice",
                    cluster_title="Duplicate",
                    command_text="duplicate",
                    idempotency_key="resolution-command-1",
                )
                session.add(duplicate)
                with pytest.raises(IntegrityError):
                    await session.commit()
                await session.rollback()
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_support_action_routes_create_list_and_update_status(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())

        try:
            created = await routes.create_support_action(
                routes.SupportActionCreateRequest(
                    cluster_id="tag:export|timeout",
                    cluster_title="Export + Timeout",
                    command_text="/support.agent.execute\ncluster: Export + Timeout",
                    workflow={"cluster": {"id": "tag:export|timeout"}},
                ),
                ctx=_ctx(),
            )
            listed = await routes.list_support_actions(limit=20, ctx=_ctx())
            other_tenant = await routes.list_support_actions(
                limit=20,
                ctx=_ctx(tenant_id="tenant-b"),
            )
            updated = await routes.update_support_action_status(
                created["action"]["id"],
                routes.SupportActionStatusRequest(status="approved"),
                ctx=_ctx(user_id="reviewer"),
            )
            ready = await routes.update_support_action_status(
                created["action"]["id"],
                routes.SupportActionStatusRequest(status="ready_to_execute"),
                ctx=_ctx(user_id="reviewer"),
            )
            executed = await routes.execute_support_action(
                created["action"]["id"],
                routes.SupportActionExecuteRequest(execution_notes="Local demo execution"),
                ctx=_ctx(user_id="operator"),
            )

            assert created["action"]["status"] == "generated"
            assert created["action"]["cluster_title"] == "Export + Timeout"
            assert [item["id"] for item in listed["actions"]] == [created["action"]["id"]]
            assert other_tenant["actions"] == []
            assert updated["action"]["status"] == "approved"
            assert updated["action"]["approved_by"] == "reviewer"
            assert updated["action"]["approved_at"] is not None
            assert ready["action"]["status"] == "ready_to_execute"
            assert ready["action"]["ready_at"] is not None
            assert executed["action"]["status"] == "executed"
            assert executed["action"]["executed_by"] == "operator"
            assert executed["action"]["executed_at"] is not None
            assert executed["action"]["execution_result"]["mode"] == "local_mock"
            assert executed["action"]["execution_result"]["artifacts"][0]["type"] == "support_macro"
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_support_action_execute_requires_ready_status(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())

        try:
            created = await routes.create_support_action(
                routes.SupportActionCreateRequest(
                    cluster_id="tag:export|timeout",
                    cluster_title="Export + Timeout",
                    command_text="/support.agent.execute\ncluster: Export + Timeout",
                    workflow={"cluster": {"id": "tag:export|timeout"}},
                ),
                ctx=_ctx(),
            )

            with pytest.raises(Exception) as exc:
                await routes.execute_support_action(
                    created["action"]["id"],
                    routes.SupportActionExecuteRequest(),
                    ctx=_ctx(user_id="operator"),
                )
            assert getattr(exc.value, "status_code", None) == 409
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_support_action_reset_clears_only_current_tenant(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())

        try:
            first = await routes.create_support_action(
                routes.SupportActionCreateRequest(
                    cluster_id="tag:export|timeout",
                    cluster_title="Export + Timeout",
                    command_text="/support.agent.execute\ncluster: Export + Timeout",
                    workflow={"cluster": {"id": "tag:export|timeout"}},
                ),
                ctx=_ctx(),
            )
            second = await routes.create_support_action(
                routes.SupportActionCreateRequest(
                    cluster_id="tag:billing|invoice",
                    cluster_title="Billing + Invoice",
                    command_text="/support.agent.execute\ncluster: Billing + Invoice",
                    workflow={"cluster": {"id": "tag:billing|invoice"}},
                ),
                ctx=_ctx(tenant_id="tenant-b"),
            )

            reset = await routes.reset_support_actions(ctx=_ctx())
            tenant_a = await routes.list_support_actions(limit=20, ctx=_ctx())
            tenant_b = await routes.list_support_actions(limit=20, ctx=_ctx(tenant_id="tenant-b"))

            assert reset["deleted_count"] == 1
            assert first["action"]["id"] not in [item["id"] for item in tenant_a["actions"]]
            assert [item["id"] for item in tenant_b["actions"]] == [second["action"]["id"]]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_support_action_status_rejects_invalid_status(self, monkeypatch):
        import app.memory.postgres as pg
        import app.routes.support as routes

        engine, Session = await _session()
        monkeypatch.setattr(pg, "AsyncSessionLocal", Session)
        monkeypatch.setattr(routes.audit_mgr, "log_event", AsyncMock())

        try:
            with pytest.raises(Exception) as exc:
                await routes.update_support_action_status(
                    "missing",
                    routes.SupportActionStatusRequest(status="published_to_zendesk"),
                    ctx=_ctx(),
                )
            assert getattr(exc.value, "status_code", None) == 400
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
