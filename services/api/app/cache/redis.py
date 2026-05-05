# services/api/app/cache/redis.py
import redis.asyncio as redis

from app.config import settings

DEFAULT_TENANT_ID = "default"


class RedisClient:
    """
    Singleton Redis connection pool.
    Used for Rate Limiting and Semantic Cache storage.
    All key operations are namespaced by tenant_id for isolation.
    """
    def __init__(self):
        self.redis = None

    async def connect(self, redis_url: str | None = None):
        if not self.redis:
            url = redis_url or settings.get_redis_url()
            # decode_responses=True means we get Strings back, not Bytes
            self.redis = redis.from_url(
                url,
                encoding="utf-8",
                decode_responses=True
            )

    async def close(self):
        if self.redis:
            await self.redis.close()

    def get_client(self):
        """Returns the raw redis client instance"""
        return self.redis

    @staticmethod
    def tenant_key(tenant_id: str, key: str) -> str:
        """
        Build a tenant-namespaced Redis key.

        Format: tenant:{tenant_id}:{key}

        Examples:
            tenant:acme:rate_limit:user123  → rate limit counter for user123 in acme
            tenant:acme:session:abc         → session data for session abc in acme
        """
        return f"tenant:{tenant_id}:{key}"

    async def get(self, key: str, tenant_id: str = DEFAULT_TENANT_ID):
        """Tenant-scoped GET."""
        return await self.redis.get(self.tenant_key(tenant_id, key))

    async def set(self, key: str, value: str, tenant_id: str = DEFAULT_TENANT_ID, ex: int = None):
        """Tenant-scoped SET with optional expiry."""
        return await self.redis.set(self.tenant_key(tenant_id, key), value, ex=ex)

    async def delete(self, key: str, tenant_id: str = DEFAULT_TENANT_ID):
        """Tenant-scoped DELETE."""
        return await self.redis.delete(self.tenant_key(tenant_id, key))

    async def incr(self, key: str, tenant_id: str = DEFAULT_TENANT_ID):
        """Tenant-scoped INCREMENT (for rate limiting)."""
        return await self.redis.incr(self.tenant_key(tenant_id, key))

    async def expire(self, key: str, seconds: int, tenant_id: str = DEFAULT_TENANT_ID):
        """Tenant-scoped EXPIRE."""
        return await self.redis.expire(self.tenant_key(tenant_id, key), seconds)


# Global instance
redis_client = RedisClient()
