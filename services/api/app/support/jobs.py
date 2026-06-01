# services/api/app/support/jobs.py
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.support.demo import seed_demo_data
from app.support.indexer import SupportIndexError, support_indexer
from app.support.models import SupportJob
from app.support.sync import SupportSyncError, support_sync_runner

logger = logging.getLogger(__name__)

SUPPORTED_SUPPORT_PROVIDERS = ("zendesk", "intercom")
SUPPORT_SYNC_INDEX_JOB = "support_sync_index"
TERMINAL_JOB_STATUSES = ("succeeded", "failed", "canceled")

SessionFactory = Callable[[], AsyncSession]


class SupportJobManager:
    """Durable support job store and status-transition helper."""

    async def start_sync_index_job(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        requested_by: str,
        providers: list[str] | None = None,
        limit: int = 100,
        seed_demo: bool = False,
    ) -> dict[str, Any]:
        now = datetime.utcnow()
        job = SupportJob(
            id=f"support-job-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            requested_by=requested_by,
            job_type=SUPPORT_SYNC_INDEX_JOB,
            providers=_normalize_providers(providers),
            limit=min(max(limit, 1), 200),
            seed_demo=seed_demo,
            status="queued",
            current_step="queued",
            result=None,
            attempt_count=0,
            max_attempts=_max_attempts(),
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    async def list_jobs(self, session: AsyncSession, *, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
        result = await session.execute(
            select(SupportJob)
            .where(SupportJob.tenant_id == tenant_id)
            .order_by(desc(SupportJob.created_at))
            .limit(min(max(limit, 1), 50))
        )
        return [self.job_to_dict(job) for job in result.scalars().all()]

    async def get_job(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        result = await session.execute(
            select(SupportJob).where(
                SupportJob.id == job_id,
                SupportJob.tenant_id == tenant_id,
            )
        )
        job = result.scalars().first()
        return self.job_to_dict(job) if job else None

    async def get_job_by_id(self, session: AsyncSession, *, job_id: str) -> dict[str, Any] | None:
        job = await session.get(SupportJob, job_id)
        return self.job_to_dict(job) if job else None

    async def job_summary(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        stale_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        result = await session.execute(
            select(SupportJob.status, func.count(SupportJob.id))
            .where(SupportJob.tenant_id == tenant_id)
            .group_by(SupportJob.status)
        )
        counts = {status: int(count) for status, count in result.all()}

        stale_count = 0
        if stale_after_seconds is not None:
            cutoff = datetime.utcnow() - timedelta(seconds=max(stale_after_seconds, 1))
            stale_count = int(
                await session.scalar(
                    select(func.count(SupportJob.id)).where(
                        SupportJob.tenant_id == tenant_id,
                        SupportJob.status == "running",
                        or_(SupportJob.locked_at.is_(None), SupportJob.locked_at < cutoff),
                    )
                )
                or 0
            )

        active_count = counts.get("queued", 0) + counts.get("running", 0)
        terminal_count = sum(counts.get(status, 0) for status in TERMINAL_JOB_STATUSES)
        return {
            "counts": counts,
            "active_count": active_count,
            "terminal_count": terminal_count,
            "dead_letter_count": counts.get("failed", 0),
            "stale_running_count": stale_count,
        }

    async def cancel_job(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        job_id: str,
    ) -> dict[str, Any] | None:
        result = await session.execute(
            select(SupportJob).where(
                SupportJob.id == job_id,
                SupportJob.tenant_id == tenant_id,
            )
        )
        job = result.scalars().first()
        if job is None:
            return None

        now = datetime.utcnow()
        if job.status in TERMINAL_JOB_STATUSES:
            return self.job_to_dict(job)

        job.cancel_requested = True
        if job.status == "queued":
            job.status = "canceled"
            job.current_step = "canceled"
            job.canceled_at = now
            job.finished_at = now
            job.locked_by = None
            job.locked_at = None
            job.next_run_at = None
        else:
            job.current_step = "cancel_requested"
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    async def retry_job(
        self,
        session: AsyncSession,
        *,
        tenant_id: str,
        job_id: str,
        requested_by: str,
    ) -> dict[str, Any] | None:
        result = await session.execute(
            select(SupportJob).where(
                SupportJob.id == job_id,
                SupportJob.tenant_id == tenant_id,
            )
        )
        original = result.scalars().first()
        if original is None:
            return None
        if original.status not in {"failed", "canceled"}:
            raise ValueError("only failed or canceled support jobs can be retried")

        now = datetime.utcnow()
        retry = SupportJob(
            id=f"support-job-{uuid.uuid4().hex[:12]}",
            tenant_id=original.tenant_id,
            requested_by=requested_by,
            job_type=original.job_type,
            providers=original.providers or [],
            limit=original.limit,
            seed_demo=bool(original.seed_demo),
            status="queued",
            current_step="queued",
            result=None,
            error_message=None,
            attempt_count=0,
            max_attempts=_max_attempts(),
            retry_of_job_id=original.id,
            next_run_at=now,
            created_at=now,
            updated_at=now,
        )
        session.add(retry)
        await session.commit()
        await session.refresh(retry)
        return self.job_to_dict(retry)

    async def claim_next_job(
        self,
        session: AsyncSession,
        *,
        worker_id: str,
        stale_after_seconds: int,
    ) -> dict[str, Any] | None:
        await self.recover_stale_running_jobs(
            session,
            stale_after_seconds=stale_after_seconds,
        )
        now = datetime.utcnow()
        result = await session.execute(
            select(SupportJob)
            .where(
                SupportJob.status == "queued",
                SupportJob.job_type == SUPPORT_SYNC_INDEX_JOB,
                or_(SupportJob.next_run_at.is_(None), SupportJob.next_run_at <= now),
            )
            .order_by(SupportJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        job = result.scalars().first()
        if job is None:
            await session.commit()
            return None

        job.status = "running"
        job.current_step = "opening_database"
        job.started_at = job.started_at or now
        job.locked_by = worker_id
        job.locked_at = now
        job.next_run_at = None
        job.attempt_count = int(job.attempt_count or 0) + 1
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    async def recover_stale_running_jobs(
        self,
        session: AsyncSession,
        *,
        stale_after_seconds: int,
    ) -> int:
        cutoff = datetime.utcnow() - timedelta(seconds=max(stale_after_seconds, 1))
        result = await session.execute(
            select(SupportJob).where(
                SupportJob.status == "running",
                or_(SupportJob.locked_at.is_(None), SupportJob.locked_at < cutoff),
            )
        )
        recovered = 0
        now = datetime.utcnow()
        for job in result.scalars().all():
            recovered += 1
            if job.cancel_requested:
                job.status = "canceled"
                job.current_step = "canceled"
                job.finished_at = now
                job.canceled_at = now
                job.error_message = "job canceled after worker lock expired"
                job.locked_by = None
                job.locked_at = None
                job.next_run_at = None
            elif int(job.attempt_count or 0) < int(job.max_attempts or 1):
                job.status = "queued"
                job.current_step = "requeued_after_stale_lock"
                job.locked_by = None
                job.locked_at = None
                job.next_run_at = now
                job.error_message = "worker lock expired; job requeued"
            else:
                job.status = "failed"
                job.current_step = "dead_lettered_after_stale_lock"
                job.finished_at = now
                job.error_message = "worker lock expired; max attempts exhausted"
                job.locked_by = None
                job.locked_at = None
                job.next_run_at = None
            job.updated_at = now
        if recovered:
            await session.flush()
        return recovered

    async def mark_step(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        step: str,
    ) -> dict[str, Any] | None:
        job = await session.get(SupportJob, job_id)
        if job is None:
            return None
        if job.cancel_requested:
            return self.job_to_dict(job)
        now = datetime.utcnow()
        job.current_step = step
        job.locked_at = now
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    async def complete_job(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        result: dict[str, Any],
        errors: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        job = await session.get(SupportJob, job_id)
        if job is None:
            return None
        if job.cancel_requested:
            return await self.mark_canceled(session, job_id=job_id, result=result)
        now = datetime.utcnow()
        job.status = "failed" if errors else "succeeded"
        job.current_step = "finished"
        job.finished_at = now
        job.result = result
        job.error_message = _error_summary(errors)
        job.locked_by = None
        job.locked_at = None
        job.next_run_at = None
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    async def fail_job(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        message: str,
        result: dict[str, Any] | None = None,
        retryable: bool = True,
    ) -> dict[str, Any] | None:
        job = await session.get(SupportJob, job_id)
        if job is None:
            return None
        now = datetime.utcnow()
        if job.cancel_requested:
            return await self.mark_canceled(session, job_id=job_id, result=result)
        if retryable and int(job.attempt_count or 0) < int(job.max_attempts or 1):
            job.status = "queued"
            job.current_step = "retry_scheduled"
            job.finished_at = None
            job.next_run_at = now + _retry_delay(job.attempt_count)
        else:
            job.status = "failed"
            job.current_step = "failed"
            job.finished_at = now
            job.next_run_at = None
        job.result = result
        job.error_message = message[:500] or "unknown job error"
        job.locked_by = None
        job.locked_at = None
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    async def mark_canceled(
        self,
        session: AsyncSession,
        *,
        job_id: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        job = await session.get(SupportJob, job_id)
        if job is None:
            return None
        now = datetime.utcnow()
        job.status = "canceled"
        job.current_step = "canceled"
        job.result = result
        job.error_message = None
        job.cancel_requested = True
        job.canceled_at = now
        job.finished_at = now
        job.locked_by = None
        job.locked_at = None
        job.next_run_at = None
        job.updated_at = now
        await session.commit()
        await session.refresh(job)
        return self.job_to_dict(job)

    def job_to_dict(self, job: SupportJob) -> dict[str, Any]:
        return {
            "id": job.id,
            "tenant_id": job.tenant_id,
            "requested_by": job.requested_by,
            "job_type": job.job_type,
            "providers": job.providers or [],
            "limit": job.limit,
            "seed_demo": job.seed_demo,
            "status": job.status,
            "created_at": _dt(job.created_at),
            "started_at": _dt(job.started_at),
            "finished_at": _dt(job.finished_at),
            "current_step": job.current_step,
            "result": job.result,
            "error_message": job.error_message,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "cancel_requested": bool(job.cancel_requested),
            "canceled_at": _dt(job.canceled_at),
            "retry_of_job_id": job.retry_of_job_id,
            "locked_by": job.locked_by,
            "locked_at": _dt(job.locked_at),
            "next_run_at": _dt(job.next_run_at),
        }


class SupportJobWorker:
    """Polls durable support jobs and executes them outside the request path."""

    def __init__(self, manager: SupportJobManager, worker_id: str | None = None) -> None:
        self._manager = manager
        self._worker_id = worker_id or f"support-worker-{uuid.uuid4().hex[:8]}"
        self._session_factory: SessionFactory | None = None
        self._poll_seconds = 2.0
        self._stale_after_seconds = 900
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        self._wake_event: asyncio.Event | None = None

    def start(
        self,
        session_factory: SessionFactory,
        *,
        poll_seconds: float = 2.0,
        stale_after_seconds: int = 900,
    ) -> None:
        if self._task is not None and not self._task.done():
            return
        self.configure(
            session_factory,
            poll_seconds=poll_seconds,
            stale_after_seconds=stale_after_seconds,
        )
        self._stop_event = asyncio.Event()
        self._wake_event = asyncio.Event()
        self._task = asyncio.create_task(self._run_loop(), name="support-job-worker")
        logger.info("support job worker started worker_id=%s", self._worker_id)

    def configure(
        self,
        session_factory: SessionFactory,
        *,
        poll_seconds: float = 2.0,
        stale_after_seconds: int = 900,
    ) -> None:
        self._session_factory = session_factory
        self._poll_seconds = max(float(poll_seconds), 0.1)
        self._stale_after_seconds = max(int(stale_after_seconds), 1)

    def kick(self) -> None:
        if self._wake_event is not None:
            self._wake_event.set()

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
        logger.info("support job worker stopped worker_id=%s", self._worker_id)

    async def process_next_job(self) -> bool:
        if self._session_factory is None:
            return False
        async with self._session_factory() as session:
            job = await self._manager.claim_next_job(
                session,
                worker_id=self._worker_id,
                stale_after_seconds=self._stale_after_seconds,
            )
        if job is None:
            return False
        await self.process_job(job["id"])
        return True

    async def process_job(self, job_id: str) -> None:
        if self._session_factory is None:
            raise RuntimeError("support job worker is not configured")

        async with self._session_factory() as session:
            job = await self._manager.get_job_by_id(session, job_id=job_id)
        if job is None:
            return

        result: dict[str, Any] = {
            "seed": None,
            "sync_runs": [],
            "index": None,
            "errors": [],
        }
        try:
            async with self._session_factory() as session:
                if await self._cancel_if_requested(job_id, result):
                    return
                if job["seed_demo"]:
                    await self._mark_step(job_id, "seeding_demo_data")
                    if await self._cancel_if_requested(job_id, result):
                        return
                    result["seed"] = await seed_demo_data(
                        session,
                        tenant_id=job["tenant_id"],
                        requested_by=job["requested_by"],
                    )

                for provider in job["providers"]:
                    if await self._cancel_if_requested(job_id, result):
                        return
                    await self._mark_step(job_id, f"syncing_{provider}")
                    try:
                        run = await support_sync_runner.sync_provider(
                            session,
                            tenant_id=job["tenant_id"],
                            provider=provider,
                            requested_by=job["requested_by"],
                            limit=job["limit"],
                        )
                        result["sync_runs"].append(run)
                    except SupportSyncError as e:
                        await session.rollback()
                        result["errors"].append({"step": "sync", "provider": provider, "error": str(e)})

                if await self._cancel_if_requested(job_id, result):
                    return
                await self._mark_step(job_id, "indexing_support_memory")
                if await self._cancel_if_requested(job_id, result):
                    return
                try:
                    result["index"] = await support_indexer.index_tickets(
                        session,
                        tenant_id=job["tenant_id"],
                        provider=job["providers"][0] if len(job["providers"]) == 1 else None,
                        limit=job["limit"],
                    )
                    for error in result["index"].get("errors", []):
                        result["errors"].append({"step": "index", **error})
                except SupportIndexError as e:
                    await session.rollback()
                    result["errors"].append({"step": "index", "error": str(e)})

            async with self._session_factory() as session:
                if await self._is_cancel_requested(job_id):
                    await self._manager.mark_canceled(session, job_id=job_id, result=result)
                    return
                await self._manager.complete_job(
                    session,
                    job_id=job_id,
                    result=result,
                    errors=result["errors"],
                )
        except Exception as e:
            logger.warning("support job failed job_id=%s: %s", job_id, e, exc_info=True)
            async with self._session_factory() as session:
                await self._manager.fail_job(
                    session,
                    job_id=job_id,
                    message=str(e)[:500] or e.__class__.__name__,
                    result=result,
                )

    async def _mark_step(self, job_id: str, step: str) -> None:
        if self._session_factory is None:
            return
        async with self._session_factory() as session:
            await self._manager.mark_step(session, job_id=job_id, step=step)

    async def _is_cancel_requested(self, job_id: str) -> bool:
        if self._session_factory is None:
            return False
        async with self._session_factory() as session:
            job = await self._manager.get_job_by_id(session, job_id=job_id)
        return bool(job and job.get("cancel_requested") and job.get("status") not in TERMINAL_JOB_STATUSES)

    async def _cancel_if_requested(self, job_id: str, result: dict[str, Any]) -> bool:
        if not await self._is_cancel_requested(job_id):
            return False
        async with self._session_factory() as session:
            await self._manager.mark_canceled(session, job_id=job_id, result=result)
        return True

    async def _run_loop(self) -> None:
        assert self._stop_event is not None
        assert self._wake_event is not None
        while not self._stop_event.is_set():
            try:
                processed = await self.process_next_job()
                if processed:
                    continue
                self._wake_event.clear()
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=self._poll_seconds)
                except asyncio.TimeoutError:
                    pass
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("support job worker loop error: %s", e, exc_info=True)
                await asyncio.sleep(self._poll_seconds)


def _normalize_providers(providers: list[str] | None) -> list[str]:
    requested = providers or list(SUPPORTED_SUPPORT_PROVIDERS)
    normalized: list[str] = []
    for provider in requested:
        value = provider.lower().strip()
        if value not in SUPPORTED_SUPPORT_PROVIDERS:
            raise ValueError(f"unsupported support provider: {provider}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def _max_attempts() -> int:
    return min(max(int(settings.SUPPORT_JOB_MAX_ATTEMPTS), 1), 10)


def _retry_delay(attempt_count: int | None) -> timedelta:
    exponent = max(int(attempt_count or 1) - 1, 0)
    seconds = min(
        int(settings.SUPPORT_JOB_RETRY_BASE_SECONDS) * (2**exponent),
        int(settings.SUPPORT_JOB_RETRY_MAX_SECONDS),
    )
    return timedelta(seconds=max(seconds, 1))


def _error_summary(errors: list[dict[str, Any]]) -> str | None:
    if not errors:
        return None
    first = errors[0].get("error") or "unknown error"
    if len(errors) == 1:
        return str(first)
    return f"{len(errors)} errors; first: {first}"


support_job_manager = SupportJobManager()
support_job_worker = SupportJobWorker(support_job_manager)
