from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker


async def _session_factory():
    import app.support.models  # noqa: F401
    from app.memory.postgres import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    return engine, session_factory


async def _event(session, *, key: str, max_attempts: int = 3, status: str = "queued"):
    from app.support.models import SupportSearchOutboxEvent

    row = SupportSearchOutboxEvent(
        idempotency_key=key,
        tenant_id="tenant-a",
        provider="zendesk",
        event_type="upsert",
        source_type="ticket",
        source_id=key,
        payload={"source_id": key},
        status=status,
        max_attempts=max_attempts,
        available_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return row


@pytest.mark.asyncio
async def test_claim_batch_is_bounded_and_records_lease():
    from app.search.worker import SearchOutboxManager

    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            await _event(session, key="one")
            await _event(session, key="two")
            await _event(session, key="three")
            manager = SearchOutboxManager()
            claimed = await manager.claim_batch(
                session,
                worker_id="worker-a",
                batch_size=2,
                lease_seconds=60,
            )

            assert len(claimed) == 2
            assert all(event.status == "processing" for event in claimed)
            assert all(event.locked_by == "worker-a" for event in claimed)
            assert all(event.attempt_count == 1 for event in claimed)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_failure_retries_then_dead_letters_at_attempt_bound():
    from app.search.worker import SearchOutboxManager

    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            row = await _event(session, key="retry-me", max_attempts=2)
            manager = SearchOutboxManager()
            await manager.claim_batch(session, worker_id="worker-a", batch_size=1, lease_seconds=60)
            transition = await manager.mark_failure(
                session,
                event_id=row.id,
                worker_id="worker-a",
                message="temporary OpenSearch throttle",
                retryable=True,
                retry_base_seconds=0,
                retry_max_seconds=0,
            )
            assert transition == "retry_scheduled"
            retry = await session.get(type(row), row.id)
            assert retry.status == "queued"
            assert retry.locked_by is None
            assert retry.attempt_count == 1

            await manager.claim_batch(session, worker_id="worker-a", batch_size=1, lease_seconds=60)
            transition = await manager.mark_failure(
                session,
                event_id=row.id,
                worker_id="worker-a",
                message="permanent mapping failure",
                retryable=True,
                retry_base_seconds=0,
                retry_max_seconds=0,
            )
            assert transition == "dead_letter"
            dead = await session.get(type(row), row.id)
            assert dead.status == "dead_letter"
            assert dead.processed_at is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stale_lease_is_requeued_or_dead_lettered():
    from app.search.worker import SearchOutboxManager

    engine, factory = await _session_factory()
    try:
        async with factory() as session:
            requeue = await _event(session, key="stale-requeue", max_attempts=3, status="processing")
            requeue.locked_by = "dead-worker"
            requeue.locked_at = datetime.utcnow() - timedelta(hours=1)
            requeue.attempt_count = 1
            dead = await _event(session, key="stale-dead", max_attempts=1, status="processing")
            dead.locked_by = "dead-worker"
            dead.locked_at = datetime.utcnow() - timedelta(hours=1)
            dead.attempt_count = 1
            await session.commit()

            recovered = await SearchOutboxManager().recover_stale(
                session,
                stale_after_seconds=60,
            )

            assert recovered == 2
            assert (await session.get(type(requeue), requeue.id)).status == "queued"
            assert (await session.get(type(dead), dead.id)).status == "dead_letter"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_worker_processes_event_and_shutdown_is_cooperative():
    from app.search.worker import SearchIndexWorker

    engine, factory = await _session_factory()
    processed: list[int] = []

    async def handler(event):
        processed.append(event.id)

    worker = SearchIndexWorker(handler, worker_id="worker-a")
    worker.configure(factory, poll_seconds=0.1, batch_size=1, lease_seconds=60)
    try:
        async with factory() as session:
            row = await _event(session, key="process-me")
            event_id = row.id

        assert await worker.process_next_batch() == 1
        assert processed == [event_id]
        async with factory() as session:
            stored = await session.get(type(row), event_id)
            assert stored.status == "succeeded"
            assert stored.locked_by is None

        worker.start(factory, poll_seconds=0.01, batch_size=1, lease_seconds=60)
        await asyncio.sleep(0)
        await worker.shutdown()
        assert worker._task is None
    finally:
        await worker.shutdown()
        await engine.dispose()
