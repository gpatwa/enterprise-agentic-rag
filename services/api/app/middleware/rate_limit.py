# services/api/app/middleware/rate_limit.py
"""
Per-tenant rate limiter using Redis sliding window.

Uses a simple fixed-window counter in Redis:
  - Key: tenant:{tenant_id}:rate_limit:{window}
  - TTL: 60 seconds (1-minute window)
  - Limit: TenantConfig.rate_limit_rpm

Can be used as a FastAPI dependency or as ASGI middleware.
"""
import logging
import time

from fastapi import Depends, HTTPException

from app.auth.tenant import TenantContext, get_tenant_context
from app.cache.redis import redis_client
from app.tenants.config import TenantConfig
from app.tenants.middleware import get_tenant_config

logger = logging.getLogger(__name__)

RATE_LIMIT_WINDOW = 60  # 1 minute


async def check_rate_limit(
    ctx: TenantContext = Depends(get_tenant_context),
    tenant_config: TenantConfig = Depends(get_tenant_config),
) -> None:
    """
    FastAPI dependency that enforces per-tenant rate limits.

    Add to any route that should be rate-limited:
        @router.post("/endpoint")
        async def handler(
            _: None = Depends(check_rate_limit),
        ):
            ...

    Raises HTTP 429 if the tenant exceeds their rate_limit_rpm.
    A rate_limit_rpm of 0 means unlimited (no limit enforced).
    """
    rpm = tenant_config.rate_limit_rpm
    if rpm <= 0:
        return  # unlimited

    # Build rate limit key: tenant:{tid}:rate_limit:{window}
    window = int(time.time()) // RATE_LIMIT_WINDOW
    rl_key = f"rate_limit:{window}"

    try:
        # Increment counter (creates key if needed)
        current = await redis_client.incr(rl_key, tenant_id=ctx.tenant_id)

        # Set TTL on first increment
        if current == 1:
            await redis_client.expire(
                rl_key, RATE_LIMIT_WINDOW + 5, tenant_id=ctx.tenant_id
            )

        if current > rpm:
            logger.warning(
                f"Rate limit exceeded for tenant={ctx.tenant_id}: "
                f"{current}/{rpm} RPM"
            )
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Maximum {rpm} requests per minute.",
                headers={"Retry-After": str(RATE_LIMIT_WINDOW)},
            )

    except HTTPException:
        raise  # re-raise 429
    except Exception as e:
        # Redis failure should not block the request
        logger.warning(f"Rate limit check failed (allowing request): {e}")
