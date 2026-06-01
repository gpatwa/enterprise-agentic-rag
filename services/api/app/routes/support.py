# services/api/app/routes/support.py
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.audit import manager as audit_mgr
from app.auth.tenant import TenantContext, get_tenant_context
from app.support.indexer import SupportIndexError, support_indexer
from app.support.models import SupportSyncRun, SupportTicket
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


def _require_admin(ctx: TenantContext) -> None:
    if ctx.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Support sync requires admin role")


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
