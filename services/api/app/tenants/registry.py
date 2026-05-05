# services/api/app/tenants/registry.py
"""
Tenant configuration registry.

Loads tenant configs from a configurable source (static dict, database,
or Redis) and caches them in-memory for fast lookup.

Source is selected via TENANT_CONFIG_SOURCE env var:
  "static"   — Hard-coded dict (dev/testing)
  "database" — PostgreSQL tenant_configs table (future)
  "redis"    — Redis hash (future)
"""
import logging

from app.tenants.config import DEFAULT_TENANT_CONFIG, TenantConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------
# Static tenant configs (used when TENANT_CONFIG_SOURCE=static).
# In production, these would be loaded from a database or Redis.
# ---------------------------------------------------------------
_STATIC_CONFIGS: dict[str, TenantConfig] = {
    "default": DEFAULT_TENANT_CONFIG,
    # Example tenant overrides:
    # "acme": TenantConfig(
    #     tenant_id="acme",
    #     llm_provider="openai",
    #     llm_model="gpt-4o",
    #     rate_limit_rpm=120,
    #     storage_quota_mb=10240,  # 10 GB
    # ),
}


class TenantRegistry:
    """
    Manages per-tenant configurations.

    Call `load()` during app startup to populate the in-memory cache.
    Call `get()` to retrieve config for a tenant (falls back to default).
    """

    def __init__(self):
        self._cache: dict[str, TenantConfig] = {}

    async def load(self, source: str = "static") -> None:
        """
        Load tenant configs from the configured source.

        Args:
            source: "static", "database", or "redis"
        """
        if source == "static":
            self._cache = dict(_STATIC_CONFIGS)
            logger.info(
                f"Loaded {len(self._cache)} tenant configs from static source"
            )

        elif source == "database":
            # Future: SELECT * FROM tenant_configs
            logger.warning(
                "Database tenant config source not yet implemented; "
                "falling back to static"
            )
            self._cache = dict(_STATIC_CONFIGS)

        elif source == "redis":
            # Future: HGETALL tenant_configs
            logger.warning(
                "Redis tenant config source not yet implemented; "
                "falling back to static"
            )
            self._cache = dict(_STATIC_CONFIGS)

        else:
            raise ValueError(f"Unknown TENANT_CONFIG_SOURCE: '{source}'")

    def get(self, tenant_id: str) -> TenantConfig:
        """
        Retrieve the config for a tenant.
        Returns DEFAULT_TENANT_CONFIG if the tenant has no explicit config.
        """
        return self._cache.get(tenant_id, DEFAULT_TENANT_CONFIG)

    def register(self, config: TenantConfig) -> None:
        """
        Add or update a tenant config in the in-memory cache.
        Useful for dynamic registration via admin API (future).
        """
        self._cache[config.tenant_id] = config
        logger.info(f"Registered tenant config: {config.tenant_id}")

    def list_tenants(self) -> list[str]:
        """Return all registered tenant IDs."""
        return list(self._cache.keys())


# Global instance
tenant_registry = TenantRegistry()
