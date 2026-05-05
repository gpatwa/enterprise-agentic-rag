# services/api/app/tenants/middleware.py
"""
FastAPI middleware / dependency to resolve per-tenant config.

Extracts tenant_id from the JWT (via TenantContext) and looks up
the TenantConfig from the registry. Attaches it to request.state
for downstream handlers.
"""
import logging

from fastapi import Depends, HTTPException

from app.auth.tenant import TenantContext, get_tenant_context
from app.tenants.config import TenantConfig
from app.tenants.registry import tenant_registry

logger = logging.getLogger(__name__)


async def get_tenant_config(
    ctx: TenantContext = Depends(get_tenant_context),
) -> TenantConfig:
    """
    FastAPI dependency that resolves the per-tenant config.

    Usage in routes:
        @router.post("/endpoint")
        async def handler(
            tc: TenantConfig = Depends(get_tenant_config),
        ):
            ...
    """
    config = tenant_registry.get(ctx.tenant_id)

    # Check if tenant is disabled
    if not config.enabled:
        logger.warning(f"Disabled tenant attempted access: {ctx.tenant_id}")
        raise HTTPException(
            status_code=403,
            detail="Tenant account is disabled.",
        )

    return config
