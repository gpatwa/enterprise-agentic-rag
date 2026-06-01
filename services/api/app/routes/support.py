# services/api/app/routes/support.py
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.audit import manager as audit_mgr
from app.auth.tenant import TenantContext, get_tenant_context
from app.config import settings
from app.support.demo import DEMO_PROVIDER, seed_demo_data
from app.support.indexer import SupportIndexError, support_indexer
from app.support.jobs import support_job_manager, support_job_worker
from app.support.models import SupportSyncRun, SupportTicket
from app.support.resolver import SupportResolveError, support_resolver
from app.support.store import support_data_store
from app.support.sync import SupportSyncError, support_sync_runner

router = APIRouter()
ADMIN_ROLES = ("admin",)


class SupportTicketResponse(BaseModel):
    id: int
    provider: str
    external_id: str
    subject: str
    description: Optional[str]
    status: Optional[str]
    priority: Optional[str]
    category: Optional[str]
    channel: Optional[str]
    requester_external_id: Optional[str]
    assignee_external_id: Optional[str]
    organization_external_id: Optional[str]
    tags: list[str]
    source_url: Optional[str]
    created_at_external: Optional[str]
    updated_at_external: Optional[str]
    last_synced_at: str


class SupportSyncRunResponse(BaseModel):
    id: int
    provider: str
    status: str
    cursor_started_at: Optional[str]
    cursor_finished_at: Optional[str]
    records_seen: int
    records_upserted: int
    records_skipped: int
    error_message: Optional[str]
    metadata: dict[str, Any]
    started_at: str
    finished_at: Optional[str]
    created_by: Optional[str]


class SupportSearchResultResponse(BaseModel):
    id: str
    score: Optional[float]
    provider: Optional[str]
    source_type: Optional[str]
    source_id: Optional[str]
    title: Optional[str]
    text: str
    status: Optional[str]
    priority: Optional[str]
    tags: list[str]
    source_url: Optional[str]
    chunk_index: Optional[int]
    chunk_count: Optional[int]


class SupportResolveRequest(BaseModel):
    question: str
    provider: Optional[str] = None
    status: Optional[str] = None
    limit: int = 6


class SupportCitationResponse(BaseModel):
    label: str
    provider: Optional[str]
    source_type: Optional[str]
    source_id: Optional[str]
    title: Optional[str]
    source_url: Optional[str]
    score: Optional[float]


class SupportResolveResponse(BaseModel):
    answer: str
    confidence: str
    citations: list[SupportCitationResponse]
    matches: list[SupportSearchResultResponse]
    next_action: str


class SupportSyncIndexJobRequest(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["zendesk", "intercom"])
    limit: int = Field(default=100, ge=1, le=200)
    seed_demo: bool = False


def _require_admin(ctx: TenantContext) -> None:
    if ctx.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Support sync requires admin role")


@router.post("/demo/seed", response_model=dict)
async def seed_support_demo(
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    index_summary: dict[str, Any] | None = None
    index_error: str | None = None
    index_status = "succeeded"
    async with AsyncSessionLocal() as session:
        seed_summary = await seed_demo_data(
            session,
            tenant_id=ctx.tenant_id,
            requested_by=ctx.user_id,
        )
        try:
            index_summary = await support_indexer.index_tickets(
                session,
                tenant_id=ctx.tenant_id,
                provider=DEMO_PROVIDER,
                limit=100,
            )
            if index_summary.get("errors"):
                index_status = "failed"
                index_error = f"{len(index_summary['errors'])} support documents failed to index"
        except Exception as e:
            await session.rollback()
            index_status = "failed"
            index_error = str(e)[:500] or e.__class__.__name__

    await _audit_demo_seed(
        ctx,
        success=index_status == "succeeded",
        start=start,
        extra={
            "seed": seed_summary,
            "index_status": index_status,
            "index_error": index_error,
        },
    )
    return {
        "seed": seed_summary,
        "index_status": index_status,
        "index": index_summary,
        "index_error": index_error,
    }


@router.post("/jobs/sync-index", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def start_sync_index_job(
    body: SupportSyncIndexJobRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            job = await support_job_manager.start_sync_index_job(
                session,
                tenant_id=ctx.tenant_id,
                requested_by=ctx.user_id,
                providers=body.providers,
                limit=body.limit,
                seed_demo=body.seed_demo,
            )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    support_job_worker.kick()
    await _audit_job_start(ctx, start, job)
    return {"job": job}


@router.get("/jobs", response_model=dict)
async def list_support_jobs(
    limit: int = Query(default=20, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        jobs = await support_job_manager.list_jobs(session, tenant_id=ctx.tenant_id, limit=limit)
    return {"jobs": jobs}


@router.get("/jobs/summary", response_model=dict)
async def get_support_jobs_summary(
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        summary = await support_job_manager.job_summary(
            session,
            tenant_id=ctx.tenant_id,
            stale_after_seconds=settings.SUPPORT_JOB_STALE_SECONDS,
        )
    return {"summary": summary}


@router.get("/jobs/{job_id}", response_model=dict)
async def get_support_job(
    job_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        job = await support_job_manager.get_job(session, tenant_id=ctx.tenant_id, job_id=job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="support job not found")
    return {"job": job}


@router.post("/jobs/{job_id}/cancel", response_model=dict)
async def cancel_support_job(
    job_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    async with AsyncSessionLocal() as session:
        job = await support_job_manager.cancel_job(
            session,
            tenant_id=ctx.tenant_id,
            job_id=job_id,
        )
    if job is None:
        await _audit_job_action(ctx, "cancel", False, start, {"id": job_id}, status.HTTP_404_NOT_FOUND)
        raise HTTPException(status_code=404, detail="support job not found")
    await _audit_job_action(ctx, "cancel", True, start, job)
    return {"job": job}


@router.post("/jobs/{job_id}/retry", response_model=dict, status_code=status.HTTP_202_ACCEPTED)
async def retry_support_job(
    job_id: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            job = await support_job_manager.retry_job(
                session,
                tenant_id=ctx.tenant_id,
                job_id=job_id,
                requested_by=ctx.user_id,
            )
    except ValueError as e:
        await _audit_job_action(ctx, "retry", False, start, {"id": job_id, "error": str(e)}, 400)
        raise HTTPException(status_code=400, detail=str(e)) from e
    if job is None:
        await _audit_job_action(ctx, "retry", False, start, {"id": job_id}, status.HTTP_404_NOT_FOUND)
        raise HTTPException(status_code=404, detail="support job not found")
    support_job_worker.kick()
    await _audit_job_action(ctx, "retry", True, start, job, status.HTTP_202_ACCEPTED)
    return {"job": job}


@router.post("/sync/{provider}", response_model=dict)
async def sync_provider(
    provider: str,
    limit: int = Query(default=100, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            run = await support_sync_runner.sync_provider(
                session,
                tenant_id=ctx.tenant_id,
                provider=provider,
                requested_by=ctx.user_id,
                limit=limit,
            )
        await _audit_sync(ctx, provider, True, start, run)
        return {"sync_run": run}
    except SupportSyncError as e:
        await _audit_sync(ctx, provider, False, start, {"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/index", response_model=dict)
async def index_support_tickets(
    provider: Optional[str] = None,
    limit: int = Query(default=100, ge=1, le=200),
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            summary = await support_indexer.index_tickets(
                session,
                tenant_id=ctx.tenant_id,
                provider=provider,
                limit=limit,
            )
        await _audit_index(ctx, True, start, summary)
        return {"index": summary}
    except SupportIndexError as e:
        await _audit_index(ctx, False, start, {"error": str(e), "provider": provider})
        raise HTTPException(status_code=503, detail=str(e)) from e


@router.get("/search", response_model=dict)
async def search_support_resolution_index(
    q: str = Query(..., min_length=2),
    provider: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
):
    try:
        results = await support_indexer.search(
            tenant_id=ctx.tenant_id,
            query=q,
            provider=provider,
            status=status,
            limit=limit,
        )
    except SupportIndexError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "results": [SupportSearchResultResponse(**result).model_dump() for result in results],
        "query": q,
        "limit": limit,
    }


@router.post("/resolve", response_model=dict)
async def resolve_support_issue(
    body: SupportResolveRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    start = time.monotonic()
    limit = min(max(body.limit, 1), 10)
    try:
        result = await support_resolver.resolve(
            tenant_id=ctx.tenant_id,
            question=body.question,
            provider=body.provider,
            status=body.status,
            limit=limit,
        )
    except SupportResolveError as e:
        await _audit_resolve(ctx, False, start, {"error": str(e), "provider": body.provider})
        raise HTTPException(status_code=503, detail=str(e)) from e

    await _audit_resolve(
        ctx,
        True,
        start,
        {
            "provider": body.provider,
            "confidence": result["confidence"],
            "match_count": len(result["matches"]),
        },
    )
    return {"resolution": SupportResolveResponse(**result).model_dump()}


@router.get("/tickets", response_model=dict)
async def list_tickets(
    provider: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        tickets, total = await support_data_store.list_tickets(
            session,
            tenant_id=ctx.tenant_id,
            provider=provider,
            status=status,
            limit=limit,
            offset=offset,
        )
    return {
        "tickets": [_ticket_to_response(ticket).model_dump() for ticket in tickets],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/sync-runs", response_model=dict)
async def list_sync_runs(
    provider: Optional[str] = None,
    limit: int = Query(default=50, ge=1, le=100),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        runs = await support_data_store.list_sync_runs(
            session,
            tenant_id=ctx.tenant_id,
            provider=provider,
            limit=limit,
        )
    return {"sync_runs": [_sync_run_to_response(run).model_dump() for run in runs]}


def _ticket_to_response(ticket: SupportTicket) -> SupportTicketResponse:
    return SupportTicketResponse(
        id=ticket.id,
        provider=ticket.provider,
        external_id=ticket.external_id,
        subject=ticket.subject,
        description=ticket.description,
        status=ticket.status,
        priority=ticket.priority,
        category=ticket.category,
        channel=ticket.channel,
        requester_external_id=ticket.requester_external_id,
        assignee_external_id=ticket.assignee_external_id,
        organization_external_id=ticket.organization_external_id,
        tags=ticket.tags or [],
        source_url=ticket.source_url,
        created_at_external=_dt(ticket.created_at_external),
        updated_at_external=_dt(ticket.updated_at_external),
        last_synced_at=_dt(ticket.last_synced_at) or "",
    )


def _sync_run_to_response(run: SupportSyncRun) -> SupportSyncRunResponse:
    return SupportSyncRunResponse(
        id=run.id,
        provider=run.provider,
        status=run.status,
        cursor_started_at=run.cursor_started_at,
        cursor_finished_at=run.cursor_finished_at,
        records_seen=run.records_seen,
        records_upserted=run.records_upserted,
        records_skipped=run.records_skipped,
        error_message=run.error_message,
        metadata=run.metadata_ or {},
        started_at=_dt(run.started_at) or "",
        finished_at=_dt(run.finished_at),
        created_by=run.created_by,
    )


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


async def _audit_sync(
    ctx: TenantContext,
    provider: str,
    success: bool,
    start: float,
    extra: dict[str, Any],
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.sync",
        method="POST",
        path=f"/api/v1/support/sync/{provider}",
        status_code=200 if success else 400,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[provider],
        extra={"provider": provider, "success": success, **extra},
    )


async def _audit_index(
    ctx: TenantContext,
    success: bool,
    start: float,
    extra: dict[str, Any],
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.index",
        method="POST",
        path="/api/v1/support/index",
        status_code=200 if success else 503,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[extra["provider"]] if extra.get("provider") else [],
        extra={"success": success, **extra},
    )


async def _audit_demo_seed(
    ctx: TenantContext,
    success: bool,
    start: float,
    extra: dict[str, Any],
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.demo_seed",
        method="POST",
        path="/api/v1/support/demo/seed",
        status_code=200,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[DEMO_PROVIDER],
        extra={"success": success, **extra},
    )


async def _audit_job_start(
    ctx: TenantContext,
    start: float,
    job: dict[str, Any],
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.job.start",
        method="POST",
        path="/api/v1/support/jobs/sync-index",
        status_code=status.HTTP_202_ACCEPTED,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=job.get("providers", []),
        extra={"job_id": job.get("id"), "seed_demo": job.get("seed_demo")},
    )


async def _audit_job_action(
    ctx: TenantContext,
    action: str,
    success: bool,
    start: float,
    job: dict[str, Any],
    status_code: int = 200,
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type=f"support.job.{action}",
        method="POST",
        path=f"/api/v1/support/jobs/{job.get('id', 'unknown')}/{action}",
        status_code=status_code,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=job.get("providers", []),
        extra={
            "job_id": job.get("id"),
            "success": success,
            "status": job.get("status"),
            "retry_of_job_id": job.get("retry_of_job_id"),
            "error": job.get("error"),
        },
    )


async def _audit_resolve(
    ctx: TenantContext,
    success: bool,
    start: float,
    extra: dict[str, Any],
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.resolve",
        method="POST",
        path="/api/v1/support/resolve",
        status_code=200 if success else 503,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[extra["provider"]] if extra.get("provider") else [],
        extra={"success": success, **extra},
    )
