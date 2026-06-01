# services/api/app/routes/support_integrations.py
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.audit import manager as audit_mgr
from app.auth.tenant import TenantContext, get_tenant_context
from app.support_integrations.catalog import SupportIntegrationCatalog
from app.support_integrations.manager import (
    SupportIntegrationError,
    support_integration_manager,
)

router = APIRouter()
ADMIN_ROLES = ("admin",)


def _require_admin(ctx: TenantContext) -> None:
    if ctx.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Support integration admin actions require the admin role",
        )


class SupportCatalogEntryResponse(BaseModel):
    provider: str
    display_name: str
    description: str
    category: str
    auth_modes: list[str]
    nango_provider_config_key: str
    direct_env_vars: list[str]
    objects: list[str]
    docs_url: Optional[str]


class SupportConnectionResponse(BaseModel):
    provider: str
    auth_mode: str
    status: str
    nango_connection_id: Optional[str]
    provider_config_key: Optional[str]
    external_account_id: Optional[str]
    metadata: dict[str, Any]
    last_health_check: Optional[str]
    error_message: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]


class UpsertSupportConnectionRequest(BaseModel):
    provider: str = Field(..., description="zendesk or intercom")
    auth_mode: str = Field(
        default="nango",
        description="nango for customer OAuth, direct_env for env-configured private deploys",
    )
    nango_connection_id: Optional[str] = None
    provider_config_key: Optional[str] = None
    external_account_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SupportTicketPreviewResponse(BaseModel):
    id: str
    subject: str
    status: Optional[str]
    requester: Optional[str]
    updated_at: Optional[str]
    url: Optional[str]


@router.get("/catalog", response_model=dict)
async def get_catalog(_: TenantContext = Depends(get_tenant_context)):
    entries = [
        SupportCatalogEntryResponse(
            provider=e.provider,
            display_name=e.display_name,
            description=e.description,
            category=e.category,
            auth_modes=list(e.auth_modes),
            nango_provider_config_key=e.nango_provider_config_key,
            direct_env_vars=list(e.direct_env_vars),
            objects=list(e.objects),
            docs_url=e.docs_url,
        ).model_dump()
        for e in SupportIntegrationCatalog.all()
    ]
    return {
        "catalog": entries,
        "support_integrations_enabled": support_integration_manager.enabled,
    }


@router.get("/connections", response_model=dict)
async def list_connections(ctx: TenantContext = Depends(get_tenant_context)):
    if not support_integration_manager.enabled:
        return {"connections": [], "support_integrations_enabled": False}

    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        return {"connections": [], "support_integrations_enabled": True}

    async with AsyncSessionLocal() as session:
        rows = await support_integration_manager.list_connections(
            session, tenant_id=ctx.tenant_id
        )
    return {
        "connections": [SupportConnectionResponse(**row).model_dump() for row in rows],
        "support_integrations_enabled": True,
    }


@router.post("/connections", response_model=dict)
async def upsert_connection(
    body: UpsertSupportConnectionRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    if not support_integration_manager.enabled:
        raise HTTPException(status_code=503, detail="Support integrations are disabled")

    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            row = await support_integration_manager.upsert_connection(
                session,
                tenant_id=ctx.tenant_id,
                provider=body.provider,
                auth_mode=body.auth_mode,
                nango_connection_id=body.nango_connection_id,
                provider_config_key=body.provider_config_key,
                external_account_id=body.external_account_id,
                metadata=body.metadata,
            )
        await _audit(ctx, "upsert", body.provider, True, start)
        return {"connection": SupportConnectionResponse(**row).model_dump()}
    except SupportIntegrationError as e:
        await _audit(ctx, "upsert", body.provider, False, start, {"error": str(e)})
        raise HTTPException(status_code=400, detail=str(e)) from e


@router.post("/connections/{provider}/test", response_model=dict)
async def test_connection(
    provider: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            result = await support_integration_manager.test_connection(
                session, tenant_id=ctx.tenant_id, provider=provider
            )
        await _audit(ctx, "test", provider, bool(result.get("ok")), start)
        return result
    except SupportIntegrationError as e:
        await _audit(ctx, "test", provider, False, start, {"error": str(e)})
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/connections/{provider}", response_model=dict)
async def delete_connection(
    provider: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    start = time.monotonic()
    async with AsyncSessionLocal() as session:
        removed = await support_integration_manager.delete_connection(
            session, tenant_id=ctx.tenant_id, provider=provider
        )
    await _audit(ctx, "remove", provider, removed, start)
    return {"removed": removed}


@router.get("/connections/{provider}/tickets", response_model=dict)
async def list_ticket_previews(
    provider: str,
    limit: int = Query(default=10, ge=1, le=50),
    ctx: TenantContext = Depends(get_tenant_context),
):
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(status_code=503, detail="database unavailable")

    try:
        async with AsyncSessionLocal() as session:
            tickets = await support_integration_manager.list_ticket_previews(
                session, tenant_id=ctx.tenant_id, provider=provider, limit=limit
            )
    except SupportIntegrationError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    return {
        "provider": provider,
        "tickets": [
            SupportTicketPreviewResponse(
                id=t.id,
                subject=t.subject,
                status=t.status,
                requester=t.requester,
                updated_at=t.updated_at,
                url=t.url,
            ).model_dump()
            for t in tickets
        ],
    }


async def _audit(
    ctx: TenantContext,
    action: str,
    provider: str,
    success: bool,
    start: float,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {"action": action, "provider": provider, "success": success}
    if extra:
        payload.update(extra)
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="support.integration.admin",
        method="POST" if action != "remove" else "DELETE",
        path=f"/api/v1/support-integrations/connections/{provider}",
        status_code=200 if success else 400,
        duration_ms=int((time.monotonic() - start) * 1000),
        sources_used=[provider],
        extra=payload,
    )
