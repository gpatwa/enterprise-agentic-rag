# services/api/app/support/jobs.py
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.support.demo import seed_demo_data
from app.support.indexer import SupportIndexError, support_indexer
from app.support.sync import SupportSyncError, support_sync_runner

logger = logging.getLogger(__name__)

SUPPORTED_SUPPORT_PROVIDERS = ("zendesk", "intercom")
TERMINAL_JOB_STATUSES = {"succeeded", "failed"}


@dataclass
class SupportJobState:
    id: str
    tenant_id: str
    requested_by: str
    providers: list[str]
    limit: int
    seed_demo: bool
    status: str = "queued"
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    current_step: str | None = None
    result: dict[str, Any] | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "requested_by": self.requested_by,
            "providers": self.providers,
            "limit": self.limit,
            "seed_demo": self.seed_demo,
            "status": self.status,
            "created_at": _dt(self.created_at),
            "started_at": _dt(self.started_at),
            "finished_at": _dt(self.finished_at),
            "current_step": self.current_step,
            "result": self.result,
            "error_message": self.error_message,
        }


class SupportJobManager:
    """Small in-process job runner for dev/demo sync-index workflows.

    This is intentionally lightweight. Production should move this contract to a durable
    queue/table so jobs survive process restarts and can run outside API workers.
    """

    def __init__(self, max_jobs: int = 100) -> None:
        self._jobs: dict[str, SupportJobState] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()
        self._max_jobs = max_jobs

    async def start_sync_index_job(
        self,
        *,
        tenant_id: str,
        requested_by: str,
        providers: list[str] | None = None,
        limit: int = 100,
        seed_demo: bool = False,
        start_background: bool = True,
    ) -> dict[str, Any]:
        job = SupportJobState(
            id=f"support-job-{uuid.uuid4().hex[:12]}",
            tenant_id=tenant_id,
            requested_by=requested_by,
            providers=_normalize_providers(providers),
            limit=min(max(limit, 1), 200),
            seed_demo=seed_demo,
        )
        async with self._lock:
            self._jobs[job.id] = job
            self._trim_locked()

        if start_background:
            task = asyncio.create_task(self._run_sync_index_job(job.id))
            self._tasks[job.id] = task
            task.add_done_callback(lambda _task, job_id=job.id: self._tasks.pop(job_id, None))
        return job.to_dict()

    async def list_jobs(self, *, tenant_id: str, limit: int = 20) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = [job for job in self._jobs.values() if job.tenant_id == tenant_id]
            jobs.sort(key=lambda job: job.created_at, reverse=True)
            return [job.to_dict() for job in jobs[: min(max(limit, 1), 50)]]

    async def get_job(self, *, tenant_id: str, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.tenant_id != tenant_id:
                return None
            return job.to_dict()

    async def _run_sync_index_job(self, job_id: str) -> None:
        job = await self._get_state(job_id)
        if job is None:
            return

        result: dict[str, Any] = {
            "seed": None,
            "sync_runs": [],
            "index": None,
            "errors": [],
        }
        await self._update_job(
            job_id,
            status="running",
            started_at=datetime.utcnow(),
            current_step="opening_database",
        )

        try:
            from app.memory import postgres as pg

            if pg.AsyncSessionLocal is None:
                raise RuntimeError("database unavailable")

            async with pg.AsyncSessionLocal() as session:
                if job.seed_demo:
                    await self._update_job(job_id, current_step="seeding_demo_data")
                    result["seed"] = await seed_demo_data(
                        session,
                        tenant_id=job.tenant_id,
                        requested_by=job.requested_by,
                    )

                for provider in job.providers:
                    await self._update_job(job_id, current_step=f"syncing_{provider}")
                    try:
                        run = await support_sync_runner.sync_provider(
                            session,
                            tenant_id=job.tenant_id,
                            provider=provider,
                            requested_by=job.requested_by,
                            limit=job.limit,
                        )
                        result["sync_runs"].append(run)
                    except SupportSyncError as e:
                        await session.rollback()
                        result["errors"].append(
                            {"step": "sync", "provider": provider, "error": str(e)}
                        )

                await self._update_job(job_id, current_step="indexing_support_memory")
                try:
                    result["index"] = await support_indexer.index_tickets(
                        session,
                        tenant_id=job.tenant_id,
                        provider=job.providers[0] if len(job.providers) == 1 else None,
                        limit=job.limit,
                    )
                    for error in result["index"].get("errors", []):
                        result["errors"].append({"step": "index", **error})
                except SupportIndexError as e:
                    await session.rollback()
                    result["errors"].append({"step": "index", "error": str(e)})

            errors = result["errors"]
            await self._update_job(
                job_id,
                status="failed" if errors else "succeeded",
                current_step="finished",
                finished_at=datetime.utcnow(),
                result=result,
                error_message=_error_summary(errors),
            )
        except Exception as e:
            logger.warning("support background job failed job_id=%s: %s", job_id, e, exc_info=True)
            await self._update_job(
                job_id,
                status="failed",
                current_step="failed",
                finished_at=datetime.utcnow(),
                result=result,
                error_message=str(e)[:500] or e.__class__.__name__,
            )

    async def _get_state(self, job_id: str) -> SupportJobState | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def _update_job(self, job_id: str, **updates: Any) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            for key, value in updates.items():
                setattr(job, key, value)

    def _trim_locked(self) -> None:
        if len(self._jobs) <= self._max_jobs:
            return
        ordered = sorted(self._jobs.values(), key=lambda job: job.created_at)
        for job in ordered[: len(self._jobs) - self._max_jobs]:
            task = self._tasks.get(job.id)
            if task is not None and not task.done():
                continue
            self._jobs.pop(job.id, None)


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


def _error_summary(errors: list[dict[str, Any]]) -> str | None:
    if not errors:
        return None
    first = errors[0].get("error") or "unknown error"
    if len(errors) == 1:
        return str(first)
    return f"{len(errors)} errors; first: {first}"


support_job_manager = SupportJobManager()
