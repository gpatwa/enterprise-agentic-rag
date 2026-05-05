# services/api/tests/test_security_hardening.py
"""
Enterprise security tests:

- PII detector + redactor (T1.7)
- Schema column-allowlist validation (T1.8)
- SQL safety against prompt-injection / jailbreak attempts (T2.13)
- Audit log table presence (T1.1)
- Iterative clarification node existence (T1.9)
- Right-to-be-forgotten route registration (T2.11)
- Privacy / audit / rate-limit / CORS config invariants

These tests run without Postgres, Redis, or any external service —
they exercise pure-python logic only.
"""
import os

import pytest

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "true")


# ── PII detector + redactor (T1.7) ───────────────────────────────────


class TestPiiDetector:
    def test_email_detected(self):
        from app.privacy.pii import contains_pii, detect

        assert contains_pii("contact me at jane.doe@acme.com please")
        assert "EMAIL" in detect("jane@acme.com")

    def test_ssn_detected(self):
        from app.privacy.pii import detect

        assert "SSN" in detect("SSN 123-45-6789")

    def test_credit_card_detected(self):
        from app.privacy.pii import detect

        assert "CC" in detect("card 4242 4242 4242 4242")

    def test_ip_detected(self):
        from app.privacy.pii import detect

        assert "IP" in detect("server is at 10.0.0.1")

    def test_no_false_positives(self):
        from app.privacy.pii import contains_pii

        assert not contains_pii("Top 10 product categories by revenue last quarter")
        assert not contains_pii("")
        assert not contains_pii("just a normal sentence")

    def test_redactor_replaces_with_placeholder(self):
        from app.privacy.pii import redact

        out, fired = redact("email: gopal@compass.ai")
        assert "[EMAIL]" in out
        assert "gopal@compass.ai" not in out
        assert "EMAIL" in fired

    def test_redactor_preserves_unrelated_text(self):
        from app.privacy.pii import redact

        out, _ = redact("Revenue is up 14%.")
        assert out == "Revenue is up 14%."


# ── SQL prompt-injection / jailbreak defenses (T2.13) ───────────────


class TestSqlInjectionDefenses:
    @pytest.mark.parametrize(
        "evil_sql",
        [
            "DROP TABLE olist_orders",
            "DELETE FROM olist_orders WHERE 1=1",
            "INSERT INTO olist_orders VALUES (1)",
            "UPDATE olist_orders SET status='hacked'",
            "TRUNCATE TABLE olist_orders",
            "GRANT ALL ON olist_orders TO public",
            "ALTER TABLE olist_orders DROP COLUMN customer_id",
            "CREATE TABLE x AS SELECT * FROM olist_orders",
            "SELECT pg_sleep(60)",
            "COPY olist_orders TO '/tmp/leak'",
            "SELECT 1; DROP TABLE olist_orders",
            "SELECT * FROM users_passwords",  # unknown table
        ],
    )
    def test_rejects_malicious_sql(self, evil_sql: str):
        from app.analytics.safety import validate_sql

        ok, err = validate_sql(evil_sql)
        assert ok is False, f"Should have rejected: {evil_sql!r} (err: {err})"

    def test_unknown_column_rejected(self):
        from app.analytics.safety import validate_sql

        ok, err = validate_sql(
            "SELECT olist_orders.password FROM olist_orders LIMIT 5"
        )
        assert ok is False
        assert "olist_orders.password" in err

    def test_known_qualified_column_allowed(self):
        from app.analytics.safety import validate_sql

        ok, err = validate_sql(
            "SELECT olist_orders.order_status FROM olist_orders LIMIT 5"
        )
        assert ok is True, err


# ── Audit log model (T1.1) ──────────────────────────────────────────


class TestAuditLog:
    def test_model_imports(self):
        from app.audit.models import AuditLog

        assert AuditLog.__tablename__ == "audit_log"

    def test_required_columns_present(self):
        from app.audit.models import AuditLog

        cols = {c.name for c in AuditLog.__table__.columns}
        for needed in (
            "tenant_id",
            "user_id",
            "role",
            "event_type",
            "method",
            "path",
            "status_code",
            "duration_ms",
            "pii_redacted",
            "sources_used",
            "created_at",
        ):
            assert needed in cols, f"missing column {needed}"

    def test_indexes_for_compliance_queries(self):
        from app.audit.models import AuditLog

        idx_names = {i.name for i in AuditLog.__table__.indexes}
        # We need fast lookups by tenant + by user + by event type for SOC2 evidence
        assert "idx_audit_tenant_created" in idx_names
        assert "idx_audit_user_created" in idx_names
        assert "idx_audit_event_type_created" in idx_names

    def test_manager_log_event_signature(self):
        import inspect

        from app.audit import manager

        sig = inspect.signature(manager.log_event)
        for required in (
            "tenant_id",
            "user_id",
            "event_type",
            "sources_used",
            "pii_redacted",
        ):
            assert required in sig.parameters


# ── Iterative clarification node (T1.9) ─────────────────────────────


class TestClarifyNode:
    def test_node_imports(self):
        from app.agents.nodes.clarify import clarify_node

        assert callable(clarify_node)

    def test_returns_no_clarification_when_disabled(self):
        import asyncio

        from app.agents.nodes.clarify import clarify_node

        # Default is disabled
        result = asyncio.run(
            clarify_node({"current_query": "What is revenue?"}, config=None)
        )
        assert result["needs_clarification"] is False
        assert result["clarification_question"] == ""


# ── Privacy + auth route registration (T2.11, T1.6) ────────────────


class TestRouteRegistration:
    def test_privacy_route_module_imports(self):
        # Module must import; the actual app.include_router happens in main.py
        import app.routes.privacy as privacy_routes

        assert hasattr(privacy_routes, "router")
        # The forget endpoint must be registered
        paths = {r.path for r in privacy_routes.router.routes}
        assert any("/users/" in p and "/data" in p for p in paths)

    def test_audit_route_module_imports(self):
        import app.routes.audit as audit_routes

        assert hasattr(audit_routes, "router")
        paths = {r.path for r in audit_routes.router.routes}
        assert "/log" in paths

    def test_auth_has_refresh_endpoint(self):
        import app.routes.auth as auth_routes

        paths = {r.path for r in auth_routes.router.routes}
        assert "/refresh" in paths
        assert "/token" in paths

    def test_jwt_refresh_token_helpers_exist(self):
        from app.auth.jwt import create_refresh_token, verify_refresh_token

        token = create_refresh_token(user_id="u1", role="admin", tenant_id="t1")
        assert isinstance(token, str)
        # Roundtrip
        payload = verify_refresh_token(token)
        assert payload["sub"] == "u1"
        assert payload["role"] == "admin"
        assert payload["tenant_id"] == "t1"
        assert payload["type"] == "refresh"

    def test_access_token_default_ttl_is_one_hour(self):
        from app.auth.jwt import DEFAULT_ACCESS_TTL

        assert DEFAULT_ACCESS_TTL == 3600


# ── CORS config sanity (T1.3) ───────────────────────────────────────


class TestCorsConfig:
    def test_cors_setting_exists(self):
        from app.config import settings

        assert hasattr(settings, "CORS_ORIGINS")


# ── Read-only DB role (T2.10) ───────────────────────────────────────


class TestReadOnlyRole:
    def test_analytics_engine_uses_read_only_options(self):
        """
        Analytics engine must set default_transaction_read_only=on at
        connect time so leaked DML (UPDATE/DELETE) is rejected by the DB
        even if app-level safety somehow missed it. Defense in depth.
        """
        import inspect

        from app.analytics import engine

        src = inspect.getsource(engine)
        assert "default_transaction_read_only=on" in src
        assert "statement_timeout" in src


# ── Redis tenant isolation (T2.12) ──────────────────────────────────


class TestRedisTenantIsolation:
    def test_tenant_key_format(self):
        from app.cache.redis import redis_client

        assert redis_client.tenant_key("tA", "session") == "tenant:tA:session"
        assert redis_client.tenant_key("tB", "session") == "tenant:tB:session"
        # Different tenants → different keys
        assert redis_client.tenant_key("tA", "k") != redis_client.tenant_key("tB", "k")


# ── Rate limit dependency (T1.2) ────────────────────────────────────


class TestRateLimitDependency:
    def test_dep_exists(self):
        from app.middleware.rate_limit import check_rate_limit

        assert callable(check_rate_limit)

    def test_chat_route_uses_rate_limit(self):
        # Verify by source inspection — the dep is wired at the route level
        import inspect

        from app.routes import chat

        src = inspect.getsource(chat)
        assert "check_rate_limit" in src
        assert "_rl: None = Depends(check_rate_limit)" in src
