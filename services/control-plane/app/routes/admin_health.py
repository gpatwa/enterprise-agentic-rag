# services/control-plane/app/routes/admin_health.py
"""
Health and admin dashboard endpoints for the control plane.
"""
from fastapi import APIRouter, Depends, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select

from .. import db as db_module
from ..auth.jwt import require_admin
from ..models.data_plane import DataPlane
from ..models.tenant import Tenant

router = APIRouter()


@router.get("/liveness")
async def liveness():
    """Control plane liveness probe."""
    return {"status": "ok"}


@router.get("/readiness")
async def readiness():
    """Control plane readiness probe — checks database connectivity."""
    try:
        async with db_module.AsyncSessionLocal() as session:
            await session.execute(select(func.count(Tenant.id)))
        return {"status": "ready"}
    except Exception as e:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            content={"status": "not_ready", "error": str(e)},
            status_code=503,
        )


@router.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    """Prometheus scrape endpoint for process/runtime metrics."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@router.get("/dashboard")
async def admin_dashboard(_admin: dict = Depends(require_admin)):
    """
    Admin dashboard — aggregated status of all data planes and tenants.
    """
    async with db_module.AsyncSessionLocal() as session:
        # Count tenants
        tenant_result = await session.execute(select(func.count(Tenant.id)))
        total_tenants = tenant_result.scalar()

        enabled_result = await session.execute(
            select(func.count(Tenant.id)).where(Tenant.enabled == True)  # noqa: E712
        )
        enabled_tenants = enabled_result.scalar()

        # Count data planes by status
        dp_result = await session.execute(select(DataPlane))
        data_planes = dp_result.scalars().all()

        status_counts = {}
        for dp in data_planes:
            status_counts[dp.status] = status_counts.get(dp.status, 0) + 1

    return {
        "tenants": {
            "total": total_tenants,
            "enabled": enabled_tenants,
        },
        "data_planes": {
            "total": len(data_planes),
            "by_status": status_counts,
            "details": [
                {
                    "id": dp.id,
                    "tenant_id": dp.tenant_id,
                    "status": dp.status,
                    "version": dp.version,
                    "last_heartbeat": dp.last_heartbeat_at.isoformat() if dp.last_heartbeat_at else None,
                }
                for dp in data_planes
            ],
        },
    }
