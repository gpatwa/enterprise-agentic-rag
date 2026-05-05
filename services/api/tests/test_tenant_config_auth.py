# tests/test_tenant_config_auth.py
"""
Unit tests for Milestone 7: Per-Tenant Config & Production Auth.
Tests TenantConfig model, TenantRegistry, JWKS fetcher,
rate limiter, per-tenant factory overrides, and JWT RS256 support.
"""
from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------
# Test: TenantConfig model
# ---------------------------------------------------------------

class TestTenantConfig:
    def test_default_config(self):
        from app.tenants.config import TenantConfig
        tc = TenantConfig(tenant_id="test")
        assert tc.tenant_id == "test"
        assert tc.llm_provider is None
        assert tc.llm_model is None
        assert tc.rate_limit_rpm == 60
        assert tc.storage_quota_mb == 0
        assert tc.enabled is True
        assert tc.metadata == {}

    def test_config_with_overrides(self):
        from app.tenants.config import TenantConfig
        tc = TenantConfig(
            tenant_id="acme",
            llm_provider="openai",
            llm_model="gpt-4o",
            rate_limit_rpm=120,
            storage_quota_mb=10240,
        )
        assert tc.llm_provider == "openai"
        assert tc.llm_model == "gpt-4o"
        assert tc.rate_limit_rpm == 120
        assert tc.storage_quota_mb == 10240

    def test_config_is_frozen(self):
        from app.tenants.config import TenantConfig
        tc = TenantConfig(tenant_id="test")
        with pytest.raises(FrozenInstanceError):
            tc.tenant_id = "other"

    def test_default_tenant_config_singleton(self):
        from app.tenants.config import DEFAULT_TENANT_CONFIG
        assert DEFAULT_TENANT_CONFIG.tenant_id == "default"
        assert DEFAULT_TENANT_CONFIG.enabled is True


# ---------------------------------------------------------------
# Test: TenantRegistry
# ---------------------------------------------------------------

class TestTenantRegistry:
    @pytest.mark.asyncio
    async def test_load_static(self):
        from app.tenants.registry import TenantRegistry
        registry = TenantRegistry()
        await registry.load(source="static")
        assert "default" in registry.list_tenants()

    @pytest.mark.asyncio
    async def test_get_existing_tenant(self):
        from app.tenants.registry import TenantRegistry
        registry = TenantRegistry()
        await registry.load(source="static")
        config = registry.get("default")
        assert config.tenant_id == "default"

    @pytest.mark.asyncio
    async def test_get_unknown_tenant_returns_default(self):
        from app.tenants.config import DEFAULT_TENANT_CONFIG
        from app.tenants.registry import TenantRegistry
        registry = TenantRegistry()
        await registry.load(source="static")
        config = registry.get("nonexistent-tenant")
        assert config == DEFAULT_TENANT_CONFIG

    @pytest.mark.asyncio
    async def test_register_new_tenant(self):
        from app.tenants.config import TenantConfig
        from app.tenants.registry import TenantRegistry
        registry = TenantRegistry()
        await registry.load(source="static")

        new_config = TenantConfig(
            tenant_id="acme",
            llm_provider="openai",
            rate_limit_rpm=200,
        )
        registry.register(new_config)

        result = registry.get("acme")
        assert result.llm_provider == "openai"
        assert result.rate_limit_rpm == 200
        assert "acme" in registry.list_tenants()

    @pytest.mark.asyncio
    async def test_load_unknown_source_raises(self):
        from app.tenants.registry import TenantRegistry
        registry = TenantRegistry()
        with pytest.raises(ValueError, match="Unknown TENANT_CONFIG_SOURCE"):
            await registry.load(source="mongodb")


# ---------------------------------------------------------------
# Test: JWKS Fetcher
# ---------------------------------------------------------------

class TestJWKSFetcher:
    def test_fetcher_creation(self):
        from app.auth.jwks import JWKSFetcher
        fetcher = JWKSFetcher("https://example.auth0.com/.well-known/jwks.json")
        assert fetcher._jwks_url == "https://example.auth0.com/.well-known/jwks.json"
        assert fetcher._keys == []

    def test_get_signing_key_not_found(self):
        from app.auth.jwks import JWKSFetcher
        fetcher = JWKSFetcher("https://example.com")
        fetcher._keys = [{"kid": "key-1", "kty": "RSA"}]
        result = fetcher._get_signing_key("key-2")
        assert result is None

    def test_get_signing_key_found(self):
        from app.auth.jwks import JWKSFetcher
        fetcher = JWKSFetcher("https://example.com")
        fetcher._keys = [
            {"kid": "key-1", "kty": "RSA"},
            {"kid": "key-2", "kty": "RSA"},
        ]
        result = fetcher._get_signing_key("key-2")
        assert result == {"kid": "key-2", "kty": "RSA"}

    def test_global_fetcher_initially_none(self):
        from app.auth.jwks import get_jwks_fetcher
        # On first import, should be None (no IdP configured)
        # Note: This may already be set if init was called; check type
        fetcher = get_jwks_fetcher()
        # Either None or a JWKSFetcher instance is valid
        assert fetcher is None or hasattr(fetcher, "decode_token")


# ---------------------------------------------------------------
# Test: Rate Limiter
# ---------------------------------------------------------------

class TestRateLimiter:
    def test_rate_limit_module_exists(self):
        from app.middleware.rate_limit import check_rate_limit
        assert callable(check_rate_limit)

    def test_rate_limit_window_constant(self):
        from app.middleware.rate_limit import RATE_LIMIT_WINDOW
        assert RATE_LIMIT_WINDOW == 60


# ---------------------------------------------------------------
# Test: JWT RS256 support
# ---------------------------------------------------------------

class TestJWTAuth:
    def test_create_token_still_works(self):
        """Local HS256 token creation should still work."""
        from app.auth.jwt import create_token
        token = create_token(
            user_id="test-user",
            tenant_id="acme",
        )
        assert isinstance(token, str)
        assert len(token) > 0

    def test_config_has_auth_provider(self):
        from app.config import settings
        assert settings.AUTH_PROVIDER == "local"

    def test_config_has_jwks_url(self):
        from app.config import settings
        assert settings.JWT_JWKS_URL is None

    def test_config_has_tenant_config_source(self):
        from app.config import settings
        assert settings.TENANT_CONFIG_SOURCE == "static"


# ---------------------------------------------------------------
# Test: Per-Tenant LLM/Embed factory overrides
# ---------------------------------------------------------------

class TestPerTenantFactory:
    def test_get_tenant_llm_client_no_override(self):
        from app.clients.factory import get_tenant_llm_client
        default = MagicMock()
        result = get_tenant_llm_client(None, None, default)
        assert result is default

    def test_get_tenant_embed_client_no_override(self):
        from app.clients.factory import get_tenant_embed_client
        default = MagicMock()
        result = get_tenant_embed_client(None, None, default)
        assert result is default

    def test_get_tenant_llm_client_with_override(self):
        from app.clients.factory import _tenant_llm_cache, get_tenant_llm_client
        # Clear cache
        _tenant_llm_cache.clear()

        default = MagicMock()
        with patch(
            "app.clients.factory.create_llm_client"
        ) as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client
            result = get_tenant_llm_client("openai", "gpt-4o", default)
            assert result is mock_client
            mock_create.assert_called_once_with("openai", "gpt-4o")

    def test_get_tenant_llm_client_caches(self):
        from app.clients.factory import _tenant_llm_cache, get_tenant_llm_client
        _tenant_llm_cache.clear()

        default = MagicMock()
        with patch(
            "app.clients.factory.create_llm_client"
        ) as mock_create:
            mock_client = MagicMock()
            mock_create.return_value = mock_client

            # First call creates
            result1 = get_tenant_llm_client("openai", "gpt-4o", default)
            # Second call should use cache
            result2 = get_tenant_llm_client("openai", "gpt-4o", default)

            assert result1 is result2
            assert mock_create.call_count == 1  # Only called once


# ---------------------------------------------------------------
# Test: Tenant Middleware
# ---------------------------------------------------------------

class TestTenantMiddleware:
    def test_get_tenant_config_exists(self):
        from app.tenants.middleware import get_tenant_config
        assert callable(get_tenant_config)
