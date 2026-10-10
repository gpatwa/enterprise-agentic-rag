# services/api/app/routes/support.py
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select
from sqlalchemy.exc import IntegrityError

from app.audit import manager as audit_mgr
from app.auth.tenant import TenantContext, get_tenant_context
from app.config import settings
from app.search.events import InteractionKind, SearchInteractionEvent, pseudonymize_principal
from app.search.persistence import persist_interaction_event
from app.support.command_policy import PolicyOutcome, evaluate_support_command
from app.support.commands import SupportCommand
from app.support.demo import DEMO_PROVIDER, seed_demo_data
from app.support.indexer import SupportIndexError, support_indexer
from app.support.insights import repeat_ticket_insights
from app.support.jobs import support_job_manager, support_job_worker
from app.support.models import SupportAction, SupportSyncRun, SupportTicket
from app.support.resolver import SupportResolveError, support_resolver
from app.support.store import support_data_store
from app.support.sync import SupportSyncError, support_sync_runner
from app.support.workflow import (
    SupportWorkflowError,
    build_repeat_resolution_workflow,
    emit_support_interaction_event,
)

router = APIRouter()
ADMIN_ROLES = ("admin",)
SUPPORT_ACTION_STATUSES = {
    "generated",
    "needs_review",
    "approved",
    "ready_to_execute",
    "executed",
    "rejected",
}


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
    vector_score: Optional[float] = None
    lexical_score: Optional[float] = None
    fusion_score: Optional[float] = None
    retrieval_source: Optional[str] = None
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


class SupportInteractionRequest(BaseModel):
    idempotency_key: str = Field(min_length=1, max_length=255)
    kind: InteractionKind
    document_id: Optional[str] = Field(default=None, max_length=255)
    request_id: Optional[str] = Field(default=None, max_length=255)
    consent_granted: bool = False
    expires_at: Optional[datetime] = None
    metadata: dict[str, str] = Field(default_factory=dict)


class SupportResolveRequest(BaseModel):
    question: str
    provider: Optional[str] = None
    status: Optional[str] = None
    limit: int = 6
    request_id: Optional[str] = Field(default=None, max_length=255)
    consent_granted: bool = False
    expires_at: Optional[datetime] = None


class SupportCitationResponse(BaseModel):
    label: str
    provider: Optional[str]
    source_type: Optional[str]
    source_id: Optional[str]
    title: Optional[str]
    source_url: Optional[str]
    score: Optional[float]


class SupportEvidenceResponse(BaseModel):
    verification_status: str = Field(min_length=1, max_length=64)
    citation_count: int = Field(ge=0)


class SupportNextActionResponse(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    explanation: str = Field(min_length=1, max_length=1000)


class SupportResolveResponse(BaseModel):
    answer: str
    confidence: str
    citations: list[SupportCitationResponse]
    matches: list[SupportSearchResultResponse]
    next_action: str
    evidence: SupportEvidenceResponse
    abstention: bool = False
    explanation: Optional[str] = Field(default=None, max_length=2000)
    next_action_data: SupportNextActionResponse


class SupportSyncIndexJobRequest(BaseModel):
    providers: list[str] = Field(default_factory=lambda: ["zendesk", "intercom"])
    limit: int = Field(default=100, ge=1, le=200)
    seed_demo: bool = False


class SupportRepeatTicketSampleResponse(BaseModel):
    provider: str
    external_id: str
    subject: str
    status: Optional[str]
    priority: Optional[str]
    source_url: Optional[str]
    updated_at_external: Optional[str]


class SupportRepeatTicketInsightResponse(BaseModel):
    id: str
    title: str
    signals: list[str]
    count: int
    share: float
    providers: list[str]
    statuses: dict[str, int]
    priorities: dict[str, int]
    tags: list[str]
    latest_updated_at: Optional[str]
    sample_tickets: list[SupportRepeatTicketSampleResponse]
    related_query: str
    deflection_candidate: bool
    potential_deflection_count: int
    recommended_action: str


class SupportRepeatWorkflowRequest(BaseModel):
    cluster_id: Optional[str] = None
    provider: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=200, ge=1, le=200)
    min_count: int = Field(default=2, ge=2, le=10)


class SupportResolutionPlaybookResponse(BaseModel):
    title: str
    status: str
    verification_status: str
    issue_signature: list[str]
    recommended_resolution: str
    resolution_steps: list[str]
    customer_response_draft: str
    confidence: str
    evidence_count: int
    citations: list[SupportCitationResponse]
    next_action: str
    guardrails: list[str]


class SupportKnowledgeGapResponse(BaseModel):
    status: str
    severity: str
    article_title: str
    recommendation: str
    rationale: str


class SupportDeflectionEstimateResponse(BaseModel):
    potential_ticket_count: int
    confidence: str
    estimated_agent_hours_saved: float
    basis: str
    rationale: str
    assumptions: list[str]


class SupportRepeatResolutionWorkflowResponse(BaseModel):
    cluster: SupportRepeatTicketInsightResponse
    query: str
    playbook: SupportResolutionPlaybookResponse
    knowledge_gap: SupportKnowledgeGapResponse
    deflection_estimate: SupportDeflectionEstimateResponse


class SupportActionCreateRequest(BaseModel):
    cluster_id: Optional[str] = None
    cluster_title: str = Field(..., min_length=1, max_length=500)
    command_text: str = Field(..., min_length=1)
    workflow: dict[str, Any] = Field(default_factory=dict)
    action_type: str = Field(default="support_agent_command", max_length=64)


class SupportActionProposalRequest(BaseModel):
    command: SupportCommand
    cluster_title: str = Field(default="Typed support resolution", min_length=1, max_length=500)
    cluster_id: Optional[str] = None
    command_text: Optional[str] = None


class SupportActionStatusRequest(BaseModel):
    status: str
    review_notes: Optional[str] = None


class SupportActionExecuteRequest(BaseModel):
    execution_notes: Optional[str] = None


class SupportActionResponse(BaseModel):
    id: str
    tenant_id: str
    created_by: str
    action_type: str
    status: str
    cluster_id: Optional[str]
    cluster_title: str
    command_text: str
    workflow: dict[str, Any]
    command_contract_version: Optional[str]
    command_payload: Optional[dict[str, Any]]
    policy_status: Optional[str]
    policy_reason: Optional[str]
    evidence_ids: Optional[list[str]]
    idempotency_key: Optional[str]
    review_notes: Optional[str]
    approved_by: Optional[str]
    approved_at: Optional[str]
    ready_at: Optional[str]
    executed_by: Optional[str]
    executed_at: Optional[str]
    execution_result: Optional[dict[str, Any]]
    rejected_at: Optional[str]
    created_at: str
    updated_at: str


def _require_admin(ctx: TenantContext) -> None:
    if ctx.role not in ADMIN_ROLES:
        raise HTTPException(status_code=403, detail="Support sync requires admin role")


@router.post("/actions", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_support_action(
    body: SupportActionCreateRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    async with AsyncSessionLocal() as session:
        action = SupportAction(
            id=f"support-action-{uuid4().hex[:12]}",
            tenant_id=ctx.tenant_id,
            created_by=ctx.user_id,
            action_type=body.action_type,
            status="generated",
            cluster_id=body.cluster_id,
            cluster_title=body.cluster_title,
            command_text=body.command_text,
            workflow=body.workflow,
        )
        session.add(action)
        await session.commit()
        await session.refresh(action)

    payload = _action_to_response(action).model_dump()
    await _audit_action(ctx, "create", True, start, payload, status.HTTP_201_CREATED)
    return {"action": payload}


@router.post("/actions/proposals", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_support_action_proposal(
    body: SupportActionProposalRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if body.command.context.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=403, detail="support command tenant mismatch")
    decision = evaluate_support_command(body.command)
    if decision.outcome is PolicyOutcome.DENY:
        raise HTTPException(status_code=403, detail=f"support command denied: {decision.reason_code.value}")
    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    command_payload = body.command.model_dump(mode="json")
    command_payload.update(policy_version="support-policy.v1", evidence_version="evidence.v1")
    start = time.monotonic()
    async with AsyncSessionLocal() as session:
        action = SupportAction(
            id=f"support-action-{uuid4().hex[:12]}", tenant_id=ctx.tenant_id,
            created_by=ctx.user_id, action_type=body.command.command_type.value,
            status="generated", cluster_id=body.cluster_id, cluster_title=body.cluster_title,
            command_text=body.command_text or body.command.command_type.value,
            workflow={"proposal": True}, command_contract_version=body.command.contract_version,
            command_payload=command_payload, policy_status=decision.outcome.value,
            policy_reason=decision.reason_code.value, evidence_ids=list(body.command.evidence_ids),
            idempotency_key=body.command.idempotency_key,
        )
        session.add(action)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail="duplicate support command idempotency key") from exc
        await session.refresh(action)
    payload = _action_to_response(action).model_dump()
    await _audit_action(ctx, "create_proposal", True, start, payload, status.HTTP_201_CREATED)
    return {"action": payload}


@router.get("/actions", response_model=dict)
async def list_support_actions(
    limit: int = Query(default=20, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(SupportAction)
            .where(SupportAction.tenant_id == ctx.tenant_id)
            .order_by(desc(SupportAction.created_at))
            .limit(limit)
        )
        actions = result.scalars().all()
    return {"actions": [_action_to_response(action).model_dump() for action in actions]}


@router.delete("/actions", response_model=dict)
async def reset_support_actions(
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            delete(SupportAction).where(SupportAction.tenant_id == ctx.tenant_id)
        )
        await session.commit()

    deleted_count = int(result.rowcount or 0)
    await _audit_action(
        ctx,
        "reset",
        True,
        start,
        {"deleted_count": deleted_count},
    )
    return {"deleted_count": deleted_count}


@router.post("/actions/{action_id}/status", response_model=dict)
async def update_support_action_status(
    action_id: str,
    body: SupportActionStatusRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    if body.status not in SUPPORT_ACTION_STATUSES:
        raise HTTPException(status_code=400, detail="unsupported support action status")
    if body.status == "executed":
        raise HTTPException(status_code=400, detail="execute support actions with the execute route")

    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        action = await session.get(SupportAction, action_id)
        if action is None or action.tenant_id != ctx.tenant_id:
            await _audit_action(
                ctx,
                "status",
                False,
                start,
                {"id": action_id, "status": body.status},
                status.HTTP_404_NOT_FOUND,
            )
            raise HTTPException(status_code=404, detail="support action not found")

        if action.command_payload:
            allowed = {
                "generated": {"approved", "rejected"},
                "approved": {"ready_to_execute"},
            }.get(action.status, set())
            if body.status not in allowed:
                raise HTTPException(status_code=409, detail="invalid support proposal state transition")

        action.status = body.status
        action.review_notes = body.review_notes
        if body.status == "approved":
            action.approved_by = ctx.user_id
            action.approved_at = now
        elif body.status == "ready_to_execute":
            action.ready_at = now
        elif body.status == "rejected":
            action.rejected_at = now
        await session.commit()
        await session.refresh(action)

    payload = _action_to_response(action).model_dump()
    if body.status in {"approved", "rejected"}:
        await emit_support_interaction_event(
            ctx=ctx,
            kind=InteractionKind.APPROVE if body.status == "approved" else InteractionKind.REJECT,
            correlation_id=action.id,
            document_id=action.id,
            consent_granted=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=90),
            metadata={"action_status": body.status},
        )
    await _audit_action(ctx, "status", True, start, payload)
    return {"action": payload}


@router.post("/actions/{action_id}/execute", response_model=dict)
async def execute_support_action(
    action_id: str,
    body: SupportActionExecuteRequest | None = None,
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    now = datetime.utcnow()
    async with AsyncSessionLocal() as session:
        action = await session.get(SupportAction, action_id)
        if action is None or action.tenant_id != ctx.tenant_id:
            await _audit_action(
                ctx,
                "execute",
                False,
                start,
                {"id": action_id, "status": "missing"},
                status.HTTP_404_NOT_FOUND,
            )
            raise HTTPException(status_code=404, detail="support action not found")
        if action.status != "ready_to_execute":
            await _audit_action(
                ctx,
                "execute",
                False,
                start,
                _action_to_response(action).model_dump(),
                status.HTTP_409_CONFLICT,
            )
            raise HTTPException(status_code=409, detail="action must be ready_to_execute first")

        action.status = "executed"
        action.executed_by = ctx.user_id
        action.executed_at = now
        action.execution_result = _mock_support_action_execution(
            action,
            executed_by=ctx.user_id,
            executed_at=now,
            notes=body.execution_notes if body else None,
        )
        await session.commit()
        await session.refresh(action)

    payload = _action_to_response(action).model_dump()
    await emit_support_interaction_event(
        ctx=ctx,
        kind=InteractionKind.EXECUTE,
        correlation_id=action.id,
        document_id=action.id,
        consent_granted=True,
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
        metadata={"action_status": "executed"},
    )
    await _audit_action(ctx, "execute", True, start, payload)
    return {"action": payload}


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


@router.get("/insights/repeats", response_model=dict)
async def get_repeat_ticket_insights(
    provider: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=200, ge=1, le=200),
    min_count: int = Query(default=2, ge=2, le=10),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    async with AsyncSessionLocal() as session:
        result = await repeat_ticket_insights(
            session,
            tenant_id=ctx.tenant_id,
            provider=provider,
            status=status,
            limit=limit,
            min_count=min_count,
        )
    return {
        "insights": [
            SupportRepeatTicketInsightResponse(**insight).model_dump()
            for insight in result["insights"]
        ],
        "summary": result["summary"],
    }


@router.post("/insights/repeats/workflow", response_model=dict)
async def build_repeat_ticket_workflow(
    body: SupportRepeatWorkflowRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            result = await build_repeat_resolution_workflow(
                session,
                tenant_id=ctx.tenant_id,
                cluster_id=body.cluster_id,
                provider=body.provider,
                status=body.status,
                limit=body.limit,
                min_count=body.min_count,
            )
    except SupportWorkflowError as e:
        await _audit_workflow(ctx, False, start, {"error": str(e), "cluster_id": body.cluster_id})
        raise HTTPException(status_code=404, detail=str(e)) from e

    await _audit_workflow(
        ctx,
        True,
        start,
        {
            "cluster_id": result["cluster"]["id"],
            "confidence": result["playbook"]["confidence"],
            "knowledge_gap": result["knowledge_gap"]["status"],
            "potential_ticket_count": result["deflection_estimate"]["potential_ticket_count"],
        },
    )
    return {"workflow": SupportRepeatResolutionWorkflowResponse(**result).model_dump()}


@router.get("/search", response_model=dict)
async def search_support_resolution_index(
    q: str = Query(..., min_length=2),
    provider: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = Query(default=10, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        async with AsyncSessionLocal() as session:
            results = await support_indexer.search(
                tenant_id=ctx.tenant_id,
                query=q,
                provider=provider,
                status=status,
                limit=limit,
                session=session,
            )
    except SupportIndexError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e

    return {
        "results": [SupportSearchResultResponse(**result).model_dump() for result in results],
        "query": q,
        "limit": limit,
    }


@router.post("/interactions", response_model=dict)
async def record_support_search_interaction(
    body: SupportInteractionRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Record an explicitly consented interaction without storing raw query text."""
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")
    occurred_at = datetime.now(timezone.utc)
    expires_at = body.expires_at or occurred_at + timedelta(days=90)
    event = SearchInteractionEvent(
        idempotency_key=body.idempotency_key,
        tenant_id=ctx.tenant_id,
        principal_pseudonym=pseudonymize_principal(
            ctx.user_id,
            tenant_id=ctx.tenant_id,
            salt=settings.JWT_SECRET_KEY,
        ),
        purpose="support-search",
        kind=body.kind,
        request_id=body.request_id,
        document_id=body.document_id,
        occurred_at=occurred_at,
        expires_at=expires_at,
        consent_granted=body.consent_granted,
        metadata=body.metadata,
    )
    async with AsyncSessionLocal() as session:
        accepted = await persist_interaction_event(session, event)
        await session.commit()
    return {"accepted": accepted, "duplicate": not accepted and body.consent_granted}


@router.post("/resolve", response_model=dict)
async def resolve_support_issue(
    body: SupportResolveRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    limit = min(max(body.limit, 1), 10)
    try:
        async with AsyncSessionLocal() as session:
            result = await support_resolver.resolve(
                tenant_id=ctx.tenant_id,
                question=body.question,
                provider=body.provider,
                status=body.status,
                limit=limit,
                session=session,
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
    correlation_id = body.request_id or f"resolution-{uuid4().hex}"
    await emit_support_interaction_event(
        ctx=ctx,
        kind=InteractionKind.RESOLVE,
        correlation_id=correlation_id,
        document_id=f"resolution:{uuid4().hex}",
        consent_granted=body.consent_granted,
        expires_at=body.expires_at or datetime.now(timezone.utc) + timedelta(days=90),
        metadata={"confidence": str(result["confidence"]), "match_count": str(len(result["matches"]))},
    )
    citations = result.get("citations", [])
    verification_status = result.get("verification_status")
    if not isinstance(verification_status, str) or not verification_status.strip():
        verification_status = result.get("citation_verification_status")
    if not isinstance(verification_status, str) or not verification_status.strip():
        verification_status = "unverified" if result.get("abstention", False) else "fallback"
    next_action = result["next_action"]
    explanation = result.get("explanation")
    if explanation is not None and not isinstance(explanation, str):
        raise HTTPException(status_code=500, detail="invalid resolution explanation")
    response = SupportResolveResponse(
        **result,
        evidence={
            "verification_status": verification_status,
            "citation_count": len(citations),
        },
        explanation=explanation,
        next_action_data={
            "name": next_action,
            "explanation": explanation or "Follow the recommended support workflow.",
        },
    )
    return {"resolution": response.model_dump()}


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


def _action_to_response(action: SupportAction) -> SupportActionResponse:
    return SupportActionResponse(
        id=action.id,
        tenant_id=action.tenant_id,
        created_by=action.created_by,
        action_type=action.action_type,
        status=action.status,
        cluster_id=action.cluster_id,
        cluster_title=action.cluster_title,
        command_text=action.command_text,
        workflow=action.workflow or {},
        command_contract_version=action.command_contract_version,
        command_payload=action.command_payload,
        policy_status=action.policy_status,
        policy_reason=action.policy_reason,
        evidence_ids=action.evidence_ids,
        idempotency_key=action.idempotency_key,
        review_notes=action.review_notes,
        approved_by=action.approved_by,
        approved_at=_dt(action.approved_at),
        ready_at=_dt(action.ready_at),
        executed_by=action.executed_by,
        executed_at=_dt(action.executed_at),
        execution_result=action.execution_result,
        rejected_at=_dt(action.rejected_at),
        created_at=_dt(action.created_at) or "",
        updated_at=_dt(action.updated_at) or "",
    )


def _mock_support_action_execution(
    action: SupportAction,
    *,
    executed_by: str,
    executed_at: datetime,
    notes: str | None,
) -> dict[str, Any]:
    workflow = action.workflow or {}
    playbook = workflow.get("playbook") if isinstance(workflow, dict) else {}
    cluster = workflow.get("cluster") if isinstance(workflow, dict) else {}
    knowledge_gap = workflow.get("knowledge_gap") if isinstance(workflow, dict) else {}
    deflection_estimate = workflow.get("deflection_estimate") if isinstance(workflow, dict) else {}
    citations = playbook.get("citations", []) if isinstance(playbook, dict) else []
    resolution_steps = playbook.get("resolution_steps", []) if isinstance(playbook, dict) else []
    evidence_count = len(citations) if isinstance(citations, list) else 0
    cluster_title = (
        cluster.get("title")
        if isinstance(cluster, dict) and cluster.get("title")
        else action.cluster_title
    )
    article_title = (
        knowledge_gap.get("article_title")
        if isinstance(knowledge_gap, dict) and knowledge_gap.get("article_title")
        else "Support resolution article"
    )
    potential_tickets = (
        deflection_estimate.get("potential_ticket_count")
        if isinstance(deflection_estimate, dict)
        else None
    )

    return {
        "mode": "local_mock",
        "receipt_version": "support-execution-receipt.v1",
        "command_version": action.command_contract_version,
        "evidence_version": (action.command_payload or {}).get("evidence_version"),
        "policy_version": (action.command_payload or {}).get("policy_version"),
        "evidence_ids": list(action.evidence_ids or []),
        "executed_by": executed_by,
        "executed_at": _dt(executed_at),
        "notes": notes,
        "artifacts": [
            {
                "type": "support_macro",
                "title": f"Macro draft: {cluster_title}",
                "status": "created_locally",
                "summary": "Prepared a reusable agent response from the cited solved cases.",
            },
            {
                "type": "kb_update",
                "title": f"KB draft: {article_title}",
                "status": "created_locally",
                "summary": "Captured the documented resolution gap for human publication review.",
            },
            {
                "type": "product_follow_up",
                "title": f"Follow-up: {cluster_title}",
                "status": "created_locally",
                "summary": "Packaged repeat-ticket evidence for support ops or product triage.",
            },
        ],
        "checks": [
            {
                "label": "Human approval",
                "status": "passed" if action.approved_by else "missing",
                "detail": f"Approved by {action.approved_by}" if action.approved_by else "Approval was not recorded.",
            },
            {
                "label": "Evidence attached",
                "status": "passed" if evidence_count > 0 else "review",
                "detail": f"{evidence_count} citation(s) included in the command.",
            },
            {
                "label": "Resolution steps",
                "status": "passed" if isinstance(resolution_steps, list) and resolution_steps else "review",
                "detail": f"{len(resolution_steps)} operational step(s) prepared."
                if isinstance(resolution_steps, list)
                else "No structured steps found.",
            },
        ],
        "impact": {
            "potential_ticket_count": potential_tickets,
            "summary": "Local execution produced reviewable artifacts only; no external systems were changed.",
        },
    }


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


async def _audit_workflow(
    ctx: TenantContext,
    success: bool,
    start: float,
    extra: dict[str, Any],
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.workflow",
        method="POST",
        path="/api/v1/support/insights/repeats/workflow",
        status_code=200 if success else 404,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[extra["cluster_id"]] if extra.get("cluster_id") else [],
        extra={"success": success, **extra},
    )


async def _audit_action(
    ctx: TenantContext,
    action: str,
    success: bool,
    start: float,
    extra: dict[str, Any],
    status_code: int = 200,
) -> None:
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type=f"support.action.{action}",
        method="POST" if action != "list" else "GET",
        path="/api/v1/support/actions",
        status_code=status_code,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[extra["cluster_id"]] if extra.get("cluster_id") else [],
        extra={
            "success": success,
            "action_id": extra.get("id"),
            "action_status": extra.get("status"),
            "cluster_title": extra.get("cluster_title"),
        },
    )
