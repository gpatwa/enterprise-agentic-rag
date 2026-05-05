# services/api/tests/test_feedback.py
"""
Tests for the in-app feedback widget endpoint.

Strategy: invoke the route function directly with a mocked TenantContext,
plus a few TestClient checks for the FastAPI integration (validation,
response_model serialization). Slack relay is monkey-patched so no
network calls happen — the assertion is on the built payload shape.
"""
from __future__ import annotations

import os
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


def _ctx(role: str = "user", tenant_id: str = "t1", user_id: str = "alice"):
    from app.auth.tenant import TenantContext

    return TenantContext(
        tenant_id=tenant_id, user_id=user_id, role=role, permissions=[]
    )


# ── Pure-logic tests (no HTTP) ────────────────────────────────────────


class TestSubmitLogic:
    @pytest.mark.asyncio
    async def test_invalid_category_400(self):
        from app.routes.feedback import FeedbackRequest, submit_feedback

        req = FeedbackRequest(message="hi", category="not-a-category")
        with pytest.raises(HTTPException) as exc:
            await submit_feedback(req, _ctx())
        assert exc.value.status_code == 400
        assert exc.value.detail["code"] == "feedback.invalid_category"

    @pytest.mark.asyncio
    async def test_relayed_false_when_webhook_unset(self, monkeypatch):
        import app.audit.manager as audit_mod
        from app.config import settings
        from app.routes.feedback import FeedbackRequest, submit_feedback

        monkeypatch.setattr(settings, "FEEDBACK_SLACK_WEBHOOK_URL", None, raising=False)
        monkeypatch.setattr(audit_mod, "log_event", AsyncMock())

        req = FeedbackRequest(message="page is slow", category="bug")
        res = await submit_feedback(req, _ctx())
        assert res.ok is True
        assert res.relayed_to_slack is False

    @pytest.mark.asyncio
    async def test_relayed_true_on_2xx(self, monkeypatch):
        import app.audit.manager as audit_mod
        from app.config import settings
        from app.routes.feedback import FeedbackRequest, submit_feedback

        # Set webhook to a marker URL so the relay path runs.
        monkeypatch.setattr(
            settings, "FEEDBACK_SLACK_WEBHOOK_URL",
            "https://hooks.slack.invalid/T0/B0/X", raising=False,
        )
        monkeypatch.setattr(audit_mod, "log_event", AsyncMock())

        # Mock the underlying httpx call.
        class _FakeResponse:
            status_code = 200
            text = "ok"

        async def fake_post(self, url, json):  # noqa: ARG002
            return _FakeResponse()

        # Patch httpx.AsyncClient.post — context manager support intact.
        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        req = FeedbackRequest(
            message="love this", category="comment",
            current_url="http://localhost:5173/sources",
        )
        res = await submit_feedback(req, _ctx())
        assert res.ok is True
        assert res.relayed_to_slack is True

    @pytest.mark.asyncio
    async def test_relayed_false_on_5xx(self, monkeypatch):
        import app.audit.manager as audit_mod
        from app.config import settings
        from app.routes.feedback import FeedbackRequest, submit_feedback

        monkeypatch.setattr(
            settings, "FEEDBACK_SLACK_WEBHOOK_URL",
            "https://hooks.slack.invalid/T/B/X", raising=False,
        )
        monkeypatch.setattr(audit_mod, "log_event", AsyncMock())

        class _Err:
            status_code = 503
            text = "slack down"

        async def fake_post(self, url, json):  # noqa: ARG002
            return _Err()

        import httpx
        monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

        req = FeedbackRequest(message="still broken", category="bug")
        res = await submit_feedback(req, _ctx())
        # 503 from Slack must NOT propagate to the user — they still get 200.
        assert res.ok is True
        assert res.relayed_to_slack is False

    @pytest.mark.asyncio
    async def test_audit_fired_with_metadata(self, monkeypatch):
        import app.audit.manager as audit_mod
        from app.config import settings
        from app.routes.feedback import FeedbackRequest, submit_feedback

        monkeypatch.setattr(settings, "FEEDBACK_SLACK_WEBHOOK_URL", None, raising=False)
        log_event = AsyncMock()
        monkeypatch.setattr(audit_mod, "log_event", log_event)

        req = FeedbackRequest(
            message="great find", category="idea",
            current_url="http://app.local/sources",
        )
        await submit_feedback(req, _ctx(role="admin", tenant_id="acme", user_id="alice"))

        log_event.assert_called_once()
        kwargs = log_event.call_args.kwargs
        assert kwargs["event_type"] == "feedback.submitted"
        assert kwargs["tenant_id"] == "acme"
        assert kwargs["user_id"] == "alice"
        assert kwargs["extra"]["category"] == "idea"
        assert kwargs["extra"]["current_url"] == "http://app.local/sources"
        assert kwargs["extra"]["relayed_to_slack"] is False


# ── Slack payload shape ───────────────────────────────────────────────


class TestSlackPayload:
    def test_block_kit_shape(self):
        from app.routes.feedback import FeedbackRequest, _build_slack_payload

        body = FeedbackRequest(
            message="please fix the typo", category="bug",
            current_url="http://app.local/welcome",
        )
        payload = _build_slack_payload(_ctx(), body)
        assert "blocks" in payload
        assert payload["blocks"][0]["type"] == "header"
        # Header includes the emoji + category label
        assert "🐛" in payload["blocks"][0]["text"]["text"]
        assert "Bug" in payload["blocks"][0]["text"]["text"]
        # Section contains the message
        assert "please fix the typo" in payload["blocks"][1]["text"]["text"]
        # Context block has user/tenant/role
        ctx_text = "".join(
            el["text"] for el in payload["blocks"][2]["elements"]
        )
        assert "alice" in ctx_text
        assert "t1" in ctx_text

    def test_user_supplied_at_mentions_neutralised(self):
        """User can't @channel everyone via the feedback widget."""
        from app.routes.feedback import FeedbackRequest, _build_slack_payload

        body = FeedbackRequest(
            message="@channel deploy is broken @here help @everyone",
            category="bug",
        )
        payload = _build_slack_payload(_ctx(), body)
        section_text = payload["blocks"][1]["text"]["text"]
        # Should NOT contain raw @channel that Slack would expand
        assert "@channel" not in section_text  # zero-width-joiner inserted
        assert "@here" not in section_text
        assert "@everyone" not in section_text

    def test_html_brackets_escaped(self):
        from app.routes.feedback import FeedbackRequest, _build_slack_payload

        body = FeedbackRequest(message="<script>alert(1)</script>", category="bug")
        payload = _build_slack_payload(_ctx(), body)
        section_text = payload["blocks"][1]["text"]["text"]
        # No raw < > characters — they're entity-encoded
        assert "<script>" not in section_text
        assert "&lt;script&gt;" in section_text


# ── HTTP integration via TestClient ───────────────────────────────────


@pytest.fixture
def client(monkeypatch):
    """Minimal app with only the feedback router + auth dependency override."""
    import app.audit.manager as audit_mod
    from app.auth.tenant import get_tenant_context
    from app.routes import feedback as feedback_routes

    monkeypatch.setattr(audit_mod, "log_event", AsyncMock())

    app = FastAPI()
    app.include_router(feedback_routes.router, prefix="/api/v1/feedback")
    app.dependency_overrides[get_tenant_context] = lambda: _ctx()
    return TestClient(app)


class TestFeedbackHTTP:
    def test_post_200_minimal_body(self, client, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "FEEDBACK_SLACK_WEBHOOK_URL", None, raising=False)
        res = client.post(
            "/api/v1/feedback", json={"message": "hello", "category": "comment"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body == {"ok": True, "relayed_to_slack": False}

    def test_post_422_missing_message(self, client):
        res = client.post("/api/v1/feedback", json={"category": "bug"})
        assert res.status_code == 422

    def test_post_422_message_too_long(self, client):
        res = client.post(
            "/api/v1/feedback",
            json={"message": "x" * 5000, "category": "bug"},
        )
        assert res.status_code == 422

    def test_post_400_invalid_category(self, client, monkeypatch):
        from app.config import settings
        monkeypatch.setattr(settings, "FEEDBACK_SLACK_WEBHOOK_URL", None, raising=False)
        res = client.post(
            "/api/v1/feedback",
            json={"message": "hi", "category": "praise"},
        )
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "feedback.invalid_category"
