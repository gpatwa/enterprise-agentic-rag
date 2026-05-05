# services/api/app/auth/tenant.py
"""
Tenant context extraction and FastAPI dependency.

Every authenticated request carries a tenant_id in the JWT.
This module provides:
  - TenantContext: dataclass holding user + tenant identity
  - get_tenant_context(): FastAPI Depends() that extracts it from the token
"""
from dataclasses import dataclass

from fastapi import Depends

from app.auth.jwt import get_current_user

# ── Default tenant for backward compatibility ────────────────────────────────
DEFAULT_TENANT_ID = "default"


@dataclass(frozen=True)
class TenantContext:
    """
    Immutable context object threaded through every request.

    Attributes:
        tenant_id:   Organisation / workspace identifier (from JWT 'tenant_id' claim).
        user_id:     Individual user identifier (from JWT 'sub' claim).
        role:        User role string (e.g. "admin", "user").
        permissions: List of permission strings (e.g. ["read", "write"]).
    """
    tenant_id: str
    user_id: str
    role: str
    permissions: list


async def get_tenant_context(
    user: dict = Depends(get_current_user),
) -> TenantContext:
    """
    FastAPI dependency that builds a TenantContext from the decoded JWT.

    Usage in a route::

        @router.post("/something")
        async def handler(ctx: TenantContext = Depends(get_tenant_context)):
            print(ctx.tenant_id, ctx.user_id)

    Tokens minted before multi-tenancy was added will lack a tenant_id claim;
    those fall back to DEFAULT_TENANT_ID ("default") so existing tokens keep working.
    """
    return TenantContext(
        tenant_id=user.get("tenant_id", DEFAULT_TENANT_ID),
        user_id=user["id"],
        role=user.get("role", "user"),
        permissions=user.get("permissions", []),
    )


# ── Data Plane context (single-tenant, no JWT resolution) ───────────────

async def get_data_plane_context(
    user_id: str = "data-plane-user",
    role: str = "user",
) -> TenantContext:
    """
    FastAPI dependency for data plane mode.

    In single-tenant data plane deployments, there is no multi-tenant
    JWT resolution. The user identity is forwarded from the control plane
    via X-User-Id / X-User-Role headers.

    Returns a TenantContext with a fixed tenant_id (the entire data plane
    belongs to one customer).
    """
    return TenantContext(
        tenant_id=DEFAULT_TENANT_ID,
        user_id=user_id,
        role=role,
        permissions=["read", "write"],
    )
