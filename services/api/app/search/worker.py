from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.support.models import SupportSearchOutboxEvent

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]
EventHandler = Callable[[SupportSearchOutboxEvent], Awaitable[Any]]


class SearchIndexWorkerError(RuntimeError):
    """Handler error with an explicit retry policy."""

    def __init__(self, message: str, *, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class SearchOutboxManager:
    """Transactional claim and state-transition operations for search events."""

    async def recover_stale(
        self,
        session: AsyncSession,
        *,
        stale_after_seconds: int,
        retry_delay_seconds: float = 0.0,
    ) -> int:
        cutoff = datetime.utcnow() - timedelta(seconds=max(stale_after_seconds, 1))
        now = datetime.utcnow()
        result = await session.execute(
            select(SupportSearchOutboxEvent).where(
                SupportSearchOutboxEvent.status == "processing",
                or_(
                    SupportSearchOutboxEvent.locked_at.is_(None),
                    SupportSearchOutboxEvent.locked_at < cutoff,
                ),
            )
        )
        recovered = 0
        for event in result.scalars().all():
            recovered += 1
            event.locked_by = None
            event.locked_at = None
            event.updated_at = now
            if int(event.attempt_count or 0) < int(event.max_attempts or 1):
                event.status = "queued"
                event.available_at = now + timedelta(seconds=max(retry_delay_seconds, 0))
                event.last_error = "worker lease expired; event requeued"
            else:
                event.status = "dead_letter"
                event.processed_at = now
                event.last_error = "worker lease expired; max attempts exhausted"
        if recovered:
            await session.flush()
        return recovered

    async def claim_batch(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        batch_size: int,
        lease_seconds: int,
    ) -> list[SupportSearchOutboxEvent]:
        await self.recover_stale(session, stale_after_seconds=lease_seconds)
        now = datetime.utcnow()
        result = await session.execute(
            select(SupportSearchOutboxEvent)
            .where(
                SupportSearchOutboxEvent.status == "queued",
                SupportSearchOutboxEvent.available_at <= now,
            )
            .order_by(SupportSearchOutboxEvent.created_at, SupportSearchOutboxEvent.id)
            .with_for_update(skip_locked=True)
            .limit(min(max(batch_size, 1), 100))
        )
        events = list(result.scalars().all())
        for event in events:
            event.status = "processing"
            event.locked_by = worker_id
            event.locked_at = now
            event.attempt_count = int(event.attempt_count or 0) + 1
            event.updated_at = now
        await session.commit()
        return events

    async def mark_succeeded(
        self,
        session: AsyncSession,
        *,
        event_id: int,
        worker_id: str,
    ) -> bool:
        event = await session.get(SupportSearchOutboxEvent, event_id)
        if not self._owns(event, worker_id):
            return False
        now = datetime.utcnow()
        event.status = "succeeded"
        event.processed_at = now
        event.locked_by = None
        event.locked_at = None
        event.updated_at = now
        await session.commit()
        return True

    async def mark_failure(
        self,
        session: AsyncSession,
        *,
        event_id: int,
        worker_id: str,
        message: str,
        retryable: bool,
        retry_base_seconds: float = 5.0,
        retry_max_seconds: float = 300.0,
    ) -> str | None:
        event = await session.get(SupportSearchOutboxEvent, event_id)
        if not self._owns(event, worker_id):
            return None
        now = datetime.utcnow()
        attempts = int(event.attempt_count or 0)
        can_retry = retryable and attempts < int(event.max_attempts or 1)
        event.last_error = message[:2000] or "search indexing failed"
        event.locked_by = None
        event.locked_at = None
        event.updated_at = now
        if can_retry:
            exponent = max(attempts - 1, 0)
            delay = min(float(retry_max_seconds), float(retry_base_seconds) * (2**exponent))
            event.status = "queued"
            event.available_at = now + timedelta(seconds=max(delay, 0))
            transition = "retry_scheduled"
        else:
            event.status = "dead_letter"
            event.processed_at = now
            transition = "dead_letter"
        await session.commit()
        return transition

    async def renew_lease(
        self,
        session: AsyncSession,
        *,
        event_id: int,
        worker_id: str,
    ) -> bool:
        event = await session.get(SupportSearchOutboxEvent, event_id)
        if not self._owns(event, worker_id):
            return False
        event.locked_at = datetime.utcnow()
        event.updated_at = event.locked_at
        await session.commit()
        return True

    @staticmethod
    def _owns(event: SupportSearchOutboxEvent | None, worker_id: str) -> bool:
        return bool(event and event.status == "processing" and event.locked_by == worker_id)


class SearchIndexWorker:
    """Runs outbox handlers outside the API request path."""

    def __init__(
        self,
        handler: EventHandler,
        *,
        manager: SearchOutboxManager | None = None,
        worker_id: str | None = None,
    ) -> None:
        self._handler = handler
        self._manager = manager or SearchOutboxManager()
        self._worker_id = worker_id or f"search-worker-{uuid.uuid4().hex[:8]}"
        self._session_factory: SessionFactory | None = None
        self._poll_seconds = 2.0
        self._batch_size = 10
        self._lease_seconds = 900
        self._retry_base_seconds = 5.0
        self._retry_max_seconds = 300.0
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None

    def configure(
        self,
        session_factory: SessionFactory,
        *,
        poll_seconds: float = 2.0,
        batch_size: int = 10,
        lease_seconds: int = 900,
        retry_base_seconds: float = 5.0,
        retry_max_seconds: float = 300.0,
    ) -> None:
        self._session_factory = session_factory
        self._poll_seconds = max(float(poll_seconds), 0.1)
        self._batch_size = min(max(int(batch_size), 1), 100)
        self._lease_seconds = max(int(lease_seconds), 1)
        self._retry_base_seconds = max(float(retry_base_seconds), 0.0)
        self._retry_max_seconds = max(float(retry_max_seconds), self._retry_base_seconds)

    def start(self, session_factory: SessionFactory, **options: Any) -> None:
        if self._task is not None and not self._task.done():
            return
        self.configure(session_factory, **options)
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="search-index-worker")
        logger.info("search index worker started worker_id=%s", self._worker_id)

    def kick(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

    @property
    def worker_id(self) -> str:
        return self._worker_id

    async def shutdown(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        self.kick()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
        self._task = None
        logger.info("search index worker stopped worker_id=%s", self._worker_id)

    async def process_next_batch(self) -> int:
        if self._session_factory is None:
            return 0
        async with self._session_factory() as session:
            events = await self._manager.claim_batch(
                session,
                worker_id=self._worker_id,
                batch_size=self._batch_size,
                lease_seconds=self._lease_seconds,
            )
        for event in events:
            await self.process_event(event.id)
        return len(events)

    async def process_event(self, event_id: int) -> None:
        if self._session_factory is None:
            raise RuntimeError("search index worker is not configured")
        async with self._session_factory() as session:
            event = await session.get(SupportSearchOutboxEvent, event_id)
        if event is None or event.status != "processing" or event.locked_by != self._worker_id:
            return
        try:
            await self._handler(event)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            retryable = bool(getattr(error, "retryable", True))
            async with self._session_factory() as session:
                await self._manager.mark_failure(
                    session,
                    event_id=event_id,
                    worker_id=self._worker_id,
                    message=str(error),
                    retryable=retryable,
                    retry_base_seconds=self._retry_base_seconds,
                    retry_max_seconds=self._retry_max_seconds,
                )
        else:
            async with self._session_factory() as session:
                await self._manager.mark_succeeded(
                    session,
                    event_id=event_id,
                    worker_id=self._worker_id,
                )

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        assert self._wake_event is not None
        while not self._stop_event.is_set():
            try:
                processed = await self.process_next_batch()
                if processed:
                    continue
                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_seconds)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as error:
                logger.warning("search index worker loop error: %s", error, exc_info=True)
                await asyncio.sleep(self._poll_seconds)
