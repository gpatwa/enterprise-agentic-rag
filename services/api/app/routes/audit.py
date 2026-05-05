# services/api/app/routes/audit.py
"""
Read-only audit log endpoint. Tenant-scoped. Admin role required.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.audit import manager
from app.auth.tenant import TenantContext, get_tenant_context

router = APIRouter()


def _require_admin(ctx: TenantContext) -> None:
    if ctx.role not in ("admin", "auditor"):
        raise HTTPException(status_code=403, detail="Audit log access requires admin role")


@router.get("/log")
async def list_audit_log(
    limit: int = 100,
    user_id: Optional[str] = None,
    event_type: Optional[str] = None,
    ctx: TenantContext = Depends(get_tenant_context),
):
    """List recent audit events, scoped to the caller's tenant."""
    _require_admin(ctx)
    return {
        "events": await manager.list_events(
            tenant_id=ctx.tenant_id,
            limit=min(limit, 1000),
            user_id=user_id,
            event_type=event_type,
        )
    }
