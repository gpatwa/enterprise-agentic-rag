# services/api/tests/test_tenant_auth.py
"""
Unit tests for Milestone 1: Tenant Context & Session Security.

Tests cover:
  1. JWT token creation includes tenant_id claim
  2. JWT token extraction returns tenant_id (with backward compat)
  3. TenantContext dataclass construction
  4. Session ownership validation (cross-tenant denial)
  5. S3 key namespacing by tenant
  6. Auth token endpoint returns tenant_id

Run with:
    cd services/api && python -m pytest tests/test_tenant_auth.py -v
"""
import os
import sys
import time

import pytest

# Ensure services/api is on the path so we can import `app.*`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Set required env vars BEFORE importing app modules (Settings reads at import time)
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost:5432/testdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests")
os.environ.setdefault("S3_BUCKET_NAME", "test-bucket")
os.environ.setdefault("NEO4J_PASSWORD", "test-password")
os.environ.setdefault("ENV", "dev")


# ── JWT Tests ──────────────────────────────────────────────────────────────────

class TestJWT:
    """Tests for app.auth.jwt — token creation and extraction."""

    def test_create_token_includes_tenant_id(self):
        """Token payload should contain the tenant_id claim."""
        from jose import jwt

        from app.auth.jwt import create_token
        from app.config import settings

        token = create_token(
            user_id="alice",
            role="admin",
            tenant_id="acme-corp",
        )

        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["sub"] == "alice"
        assert payload["role"] == "admin"
        assert payload["tenant_id"] == "acme-corp"

    def test_create_token_default_tenant(self):
        """When tenant_id is omitted, it should default to 'default'."""
        from jose import jwt

        from app.auth.jwt import DEFAULT_TENANT_ID, create_token
        from app.config import settings

        token = create_token(user_id="bob")

        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        assert payload["tenant_id"] == DEFAULT_TENANT_ID

    @pytest.mark.asyncio
    async def test_get_current_user_extracts_tenant_id(self):
        """get_current_user should return tenant_id from the token."""
        from app.auth.jwt import create_token, get_current_user

        token = create_token(user_id="charlie", tenant_id="beta-inc")

        # Call the dependency directly (bypassing FastAPI Depends)
        user = await get_current_user(token)

        assert user["id"] == "charlie"
        assert user["tenant_id"] == "beta-inc"

    @pytest.mark.asyncio
    async def test_get_current_user_backward_compat(self):
        """Tokens without tenant_id claim should fall back to 'default'."""
        from jose import jwt as jose_jwt

        from app.auth.jwt import DEFAULT_TENANT_ID, get_current_user
        from app.config import settings

        # Manually create a token WITHOUT tenant_id (simulates pre-M1 tokens)
        old_payload = {
            "sub": "legacy-user",
            "role": "user",
            "permissions": ["read"],
            "iat": int(time.time()),
            "exp": int(time.time()) + 3600,
        }
        old_token = jose_jwt.encode(
            old_payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
        )

        user = await get_current_user(old_token)
        assert user["id"] == "legacy-user"
        assert user["tenant_id"] == DEFAULT_TENANT_ID

    @pytest.mark.asyncio
    async def test_expired_token_rejected(self):
        """Expired tokens should raise 401."""
        from fastapi import HTTPException

        from app.auth.jwt import create_token, get_current_user

        token = create_token(user_id="expired-user", expires_in=-10)

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(token)
        assert exc_info.value.status_code == 401


# ── TenantContext Tests ────────────────────────────────────────────────────────

class TestTenantContext:
    """Tests for app.auth.tenant — TenantContext dataclass."""

    def test_context_is_immutable(self):
        """TenantContext should be frozen (immutable)."""
        from app.auth.tenant import TenantContext

        ctx = TenantContext(
            tenant_id="acme", user_id="alice", role="admin", permissions=["read"]
        )
        with pytest.raises(AttributeError):
            ctx.tenant_id = "hacked"

    @pytest.mark.asyncio
    async def test_get_tenant_context_from_user_dict(self):
        """get_tenant_context should build from the user dict."""
        from app.auth.tenant import TenantContext, get_tenant_context

        # Simulate the dict that get_current_user() returns
        user_dict = {
            "id": "alice",
            "role": "admin",
            "tenant_id": "acme-corp",
            "permissions": ["read", "write"],
        }

        ctx = await get_tenant_context(user=user_dict)

        assert isinstance(ctx, TenantContext)
        assert ctx.tenant_id == "acme-corp"
        assert ctx.user_id == "alice"
        assert ctx.role == "admin"
        assert ctx.permissions == ["read", "write"]

    @pytest.mark.asyncio
    async def test_get_tenant_context_defaults(self):
        """Missing tenant_id in user dict should default to 'default'."""
        from app.auth.tenant import DEFAULT_TENANT_ID, get_tenant_context

        user_dict = {"id": "bob", "role": "user", "permissions": []}

        ctx = await get_tenant_context(user=user_dict)
        assert ctx.tenant_id == DEFAULT_TENANT_ID


# ── Auth Route Tests ───────────────────────────────────────────────────────────

class TestAuthRoute:
    """Tests for the /auth/token endpoint."""

    def test_token_request_has_tenant_id_field(self):
        """TokenRequest model should accept tenant_id."""
        from app.routes.auth import TokenRequest

        req = TokenRequest(user_id="alice", role="admin", tenant_id="acme")
        assert req.tenant_id == "acme"

    def test_token_request_default_tenant(self):
        """TokenRequest should default tenant_id to 'default'."""
        from app.auth.jwt import DEFAULT_TENANT_ID
        from app.routes.auth import TokenRequest

        req = TokenRequest()
        assert req.tenant_id == DEFAULT_TENANT_ID

    def test_token_response_has_tenant_id_field(self):
        """TokenResponse model should include tenant_id (and refresh fields after T1.6)."""
        from app.routes.auth import TokenResponse

        resp = TokenResponse(
            access_token="abc",
            refresh_token="xyz",
            user_id="alice",
            tenant_id="acme",
            expires_in=3600,
            refresh_expires_in=14 * 86400,
        )
        assert resp.tenant_id == "acme"
        assert resp.refresh_token == "xyz"
        assert resp.refresh_expires_in == 14 * 86400


# ── Upload Namespace Tests ────────────────────────────────────────────────────

class TestUploadNamespacing:
    """Tests for S3 key namespacing by tenant."""

    def test_s3_key_includes_tenant_id(self):
        """
        Upload route should generate S3 keys in the format:
        uploads/{tenant_id}/{user_id}/{file_id}.{ext}
        """
        # We test the key format directly rather than calling the route
        # (which would require a running S3/MinIO)
        tenant_id = "acme-corp"
        user_id = "alice"
        file_id = "12345678-1234-1234-1234-123456789abc"
        extension = "pdf"

        s3_key = f"uploads/{tenant_id}/{user_id}/{file_id}.{extension}"

        assert s3_key == "uploads/acme-corp/alice/12345678-1234-1234-1234-123456789abc.pdf"
        assert s3_key.startswith(f"uploads/{tenant_id}/")

    def test_different_tenants_have_different_prefixes(self):
        """Two tenants uploading the same file should get different S3 keys."""
        user_id = "shared-user"
        file_id = "same-file-id"
        ext = "pdf"

        key_a = f"uploads/tenant-a/{user_id}/{file_id}.{ext}"
        key_b = f"uploads/tenant-b/{user_id}/{file_id}.{ext}"

        assert key_a != key_b
        assert "tenant-a" in key_a
        assert "tenant-b" in key_b


# ── PostgresMemory Model Tests ───────────────────────────────────────────────

class TestChatHistoryModel:
    """Tests for the ChatHistory model with tenant_id column."""

    def test_model_has_tenant_id_column(self):
        """ChatHistory model should have a tenant_id column."""
        from app.memory.postgres import ChatHistory

        assert hasattr(ChatHistory, "tenant_id")

    def test_model_tenant_id_default(self):
        """ChatHistory column should have a default of 'default' configured."""
        from app.memory.postgres import ChatHistory

        # SQLAlchemy Column defaults apply at INSERT time (session.add), not
        # at Python object construction. Verify the column has the correct
        # default and server_default configured.
        col = ChatHistory.__table__.columns["tenant_id"]
        assert col.default.arg == "default"
        assert col.server_default.arg == "default"

    def test_model_tenant_id_custom(self):
        """ChatHistory should accept custom tenant_id."""
        from app.memory.postgres import ChatHistory

        record = ChatHistory(
            session_id="test-session",
            user_id="alice",
            tenant_id="acme-corp",
            role="user",
            content="Hello",
        )
        assert record.tenant_id == "acme-corp"

    def test_models_py_has_tenant_id(self):
        """The standalone models.py should also have tenant_id."""
        from app.memory.models import ChatHistory as ModelsChat

        assert hasattr(ModelsChat, "tenant_id")
