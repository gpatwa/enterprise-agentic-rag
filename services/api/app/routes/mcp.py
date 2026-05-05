# services/api/app/routes/mcp.py
"""
HTTP admin surface for the MCP layer.

Six endpoints, all under /api/v1/mcp:

    GET    /catalog                    Public list of known servers
    GET    /connections                Tenant's stored connections (any status)
    POST   /connections                Enable: store creds, run health probe
    POST   /connections/{server}/test  Re-run health probe
    POST   /connections/{server}/disable Pause without deleting credentials
    DELETE /connections/{server}       Delete row + reap subprocess
    GET    /tools                      Tenant's currently-available MCP tools

Auth + RBAC
-----------
- Read endpoints (GET catalog/connections/tools) require auth, no role gate.
  Any tenant member can see what's wired up; credentials are NEVER returned.
- Mutations (POST/DELETE) require role in {"admin"} — same convention as the
  audit and privacy routes. We don't want regular users to enable a connector
  with their personal SaaS token; that's an org-level decision.

Error mapping
-------------
Manager exceptions carry a stable `code` field and we forward it to the
client unchanged so the frontend can match without string-parsing the
human message:

    MCPNotEnabledError              → 503  (feature disabled by ops)
    MCPConnectionNotFoundError      → 404
    MCPCapacityError                → 429  (pool full — try later)
    MCPCryptoError                  → 500  (don't leak inner detail)
    MCPError (catch-all incl. validation) → 400

Audit
-----
Every mutation emits event_type="mcp.admin" with extra={
    action: "enable|disable|remove|test", server_name, success
} so the SOC2 audit trail covers connector lifecycle. We never log the
credentials themselves — only the action and the server.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.audit import manager as audit_mgr
from app.auth.tenant import TenantContext, get_tenant_context
from app.mcp.catalog import MCPCatalog
from app.mcp.errors import (
    MCPCapacityError,
    MCPConnectionNotFoundError,
    MCPCryptoError,
    MCPError,
    MCPNotEnabledError,
)
from app.mcp.manager import mcp_manager

logger = logging.getLogger(__name__)
router = APIRouter()

ADMIN_ROLES = ("admin",)


def _require_admin(ctx: TenantContext) -> None:
    if ctx.role not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403, detail="MCP admin actions require the admin role"
        )


def _map_error_to_http(err: MCPError) -> HTTPException:
    """Translate manager exceptions to HTTP. Stable `code` flows to the body."""
    body = err.to_dict()
    if isinstance(err, MCPNotEnabledError):
        return HTTPException(status_code=503, detail=body)
    if isinstance(err, MCPConnectionNotFoundError):
        return HTTPException(status_code=404, detail=body)
    if isinstance(err, MCPCapacityError):
        return HTTPException(status_code=429, detail=body)
    if isinstance(err, MCPCryptoError):
        # Hide internal detail; keep the code stable.
        return HTTPException(
            status_code=500,
            detail={"code": err.code, "message": "internal error"},
        )
    return HTTPException(status_code=400, detail=body)


# ── Pydantic IO models ────────────────────────────────────────────────


class CatalogEntryResponse(BaseModel):
    server_name: str
    display_name: str
    description: str
    required_credentials: list[str]
    oauth_flow: Optional[str]
    docs_url: Optional[str]


class ConnectionResponse(BaseModel):
    """Tenant-visible view of a connection. Credentials are NEVER included."""

    server_name: str
    status: str
    last_health_check: Optional[str]
    error_message: Optional[str]
    created_at: str
    updated_at: str


class EnableConnectionRequest(BaseModel):
    server_name: str = Field(
        ..., description="One of MCPCatalog.names() — slack, github, notion, gdrive"
    )
    credentials: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Plaintext credentials matching the catalog entry's "
            "required_credentials. Encrypted at rest before storage."
        ),
    )


class TestConnectionResponse(BaseModel):
    ok: bool
    error_message: Optional[str]


class ToolDescriptorResponse(BaseModel):
    server_name: str
    tool_name: str
    qualified_name: str
    description: str
    input_schema: dict[str, Any]


# ── Helpers ────────────────────────────────────────────────────────────


def _strip_creds(row: dict[str, Any]) -> ConnectionResponse:
    """Convert manager row dict → tenant-visible response model."""
    return ConnectionResponse(
        server_name=row["server_name"],
        status=row["status"],
        last_health_check=row.get("last_health_check"),
        error_message=row.get("error_message"),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


async def _audit_admin(
    ctx: TenantContext,
    action: str,
    server_name: Optional[str],
    *,
    success: bool,
    extra: Optional[dict[str, Any]] = None,
    duration_ms: Optional[int] = None,
) -> None:
    """Single shape for connector admin events. Best-effort, never raises."""
    payload = {"action": action, "server_name": server_name, "success": success}
    if extra:
        payload.update(extra)
    await audit_mgr.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="mcp.admin",
        method="POST" if action != "remove" else "DELETE",
        path=f"/api/v1/mcp/connections/{server_name or ''}",
        status_code=200 if success else 400,
        duration_ms=duration_ms,
        sources_used=[server_name] if server_name else [],
        extra=payload,
    )


# ── GET /catalog ───────────────────────────────────────────────────────


@router.get("/catalog", response_model=dict)
async def get_catalog(_: TenantContext = Depends(get_tenant_context)):
    """
    Static list of MCP servers Compass ships support for. Safe to call
    by any authenticated user — no creds, no tenant data.
    """
    entries = [
        CatalogEntryResponse(
            server_name=e.server_name,
            display_name=e.display_name,
            description=e.description,
            required_credentials=list(e.required_credentials),
            oauth_flow=e.oauth_flow,
            docs_url=e.docs_url,
        ).model_dump()
        for e in MCPCatalog.all()
    ]
    return {"catalog": entries, "mcp_enabled": mcp_manager.enabled}


# ── GET /connections ───────────────────────────────────────────────────


@router.get("/connections", response_model=dict)
async def list_connections(ctx: TenantContext = Depends(get_tenant_context)):
    """All connections for the caller's tenant. No credentials in response."""
    if not mcp_manager.enabled:
        return {"connections": [], "mcp_enabled": False}
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        return {"connections": [], "mcp_enabled": True}
    async with AsyncSessionLocal() as session:
        rows = await mcp_manager.list_connections(session, tenant_id=ctx.tenant_id)
    return {
        "connections": [_strip_creds(r).model_dump() for r in rows],
        "mcp_enabled": True,
    }


# ── POST /connections ──────────────────────────────────────────────────


@router.post("/connections", response_model=dict)
async def enable_connection(
    body: EnableConnectionRequest,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Enable (or re-enable) a connection: encrypt creds, persist, health-probe.

    The probe runs synchronously so the caller learns immediately whether
    the credentials work. On health-check failure the row is still saved
    (status=error) so the user can re-test after fixing the token without
    re-typing.
    """
    _require_admin(ctx)
    if mcp_manager.enabled is False:
        raise HTTPException(
            status_code=503,
            detail={"code": "mcp.not_enabled", "message": "MCP is disabled"},
        )
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "db.unavailable", "message": "database unavailable"},
        )
    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            row = await mcp_manager.enable_connection(
                session,
                tenant_id=ctx.tenant_id,
                server_name=body.server_name,
                credentials=body.credentials,
            )
    except MCPError as e:
        await _audit_admin(
            ctx, "enable", body.server_name,
            success=False, extra={"code": e.code},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise _map_error_to_http(e) from e

    success = row["status"] == "enabled"
    await _audit_admin(
        ctx, "enable", body.server_name,
        success=success,
        extra={"final_status": row["status"]},
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return {
        "connection": _strip_creds(row).model_dump(),
    }


# ── POST /connections/{server}/test ────────────────────────────────────


@router.post("/connections/{server_name}/test", response_model=TestConnectionResponse)
async def test_connection(
    server_name: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Re-run the health probe against existing stored credentials."""
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "db.unavailable", "message": "database unavailable"},
        )
    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            ok, err = await mcp_manager.test_connection(
                session, tenant_id=ctx.tenant_id, server_name=server_name
            )
    except MCPError as e:
        await _audit_admin(
            ctx, "test", server_name,
            success=False, extra={"code": e.code},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise _map_error_to_http(e) from e

    await _audit_admin(
        ctx, "test", server_name,
        success=ok,
        extra={"error": err} if err else None,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return TestConnectionResponse(ok=ok, error_message=err)


# ── POST /connections/{server}/disable ────────────────────────────────


@router.post("/connections/{server_name}/disable", response_model=dict)
async def disable_connection(
    server_name: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Pause a connection without deleting its credentials. The agent will
    stop seeing its tools and any live subprocess gets reaped.
    """
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "db.unavailable", "message": "database unavailable"},
        )
    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            ok = await mcp_manager.disable_connection(
                session, tenant_id=ctx.tenant_id, server_name=server_name
            )
    except MCPError as e:
        await _audit_admin(
            ctx, "disable", server_name,
            success=False, extra={"code": e.code},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise _map_error_to_http(e) from e

    if not ok:
        await _audit_admin(ctx, "disable", server_name, success=False)
        raise HTTPException(
            status_code=404,
            detail={"code": "mcp.connection_not_found", "message": "no such connection"},
        )
    await _audit_admin(
        ctx, "disable", server_name,
        success=True,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return {"disabled": True}


# ── DELETE /connections/{server} ──────────────────────────────────────


@router.delete("/connections/{server_name}", response_model=dict)
async def remove_connection(
    server_name: str,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """Hard-delete the connection row and reap any live subprocess."""
    _require_admin(ctx)
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "db.unavailable", "message": "database unavailable"},
        )
    start = time.monotonic()
    try:
        async with AsyncSessionLocal() as session:
            ok = await mcp_manager.remove_connection(
                session, tenant_id=ctx.tenant_id, server_name=server_name
            )
    except MCPError as e:
        await _audit_admin(
            ctx, "remove", server_name,
            success=False, extra={"code": e.code},
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise _map_error_to_http(e) from e

    if not ok:
        await _audit_admin(ctx, "remove", server_name, success=False)
        raise HTTPException(
            status_code=404,
            detail={"code": "mcp.connection_not_found", "message": "no such connection"},
        )
    await _audit_admin(
        ctx, "remove", server_name,
        success=True,
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return {"removed": True}


# ── GET /tools ─────────────────────────────────────────────────────────


@router.get("/tools", response_model=dict)
async def list_tools(ctx: TenantContext = Depends(get_tenant_context)):
    """
    The MCP tools currently visible to this tenant's agent. Useful for
    debugging "why didn't the planner pick a Slack tool?" — if the answer
    isn't here, the planner can't see it either.
    """
    if not mcp_manager.enabled:
        return {"tools": [], "mcp_enabled": False}
    from app.memory.postgres import AsyncSessionLocal

    if AsyncSessionLocal is None:
        return {"tools": [], "mcp_enabled": True}
    try:
        async with AsyncSessionLocal() as session:
            descriptors = await mcp_manager.list_tools(
                session, tenant_id=ctx.tenant_id
            )
    except MCPError as e:
        raise _map_error_to_http(e) from e

    return {
        "tools": [
            ToolDescriptorResponse(
                server_name=d.server_name,
                tool_name=d.tool_name,
                qualified_name=d.qualified_name,
                description=d.description,
                input_schema=d.input_schema,
            ).model_dump()
            for d in descriptors
        ],
        "mcp_enabled": True,
    }
