"""The browser sends X-Demo-Visitor on demo calls; the CORS preflight must allow it or the demo fails with "Failed to fetch"."""

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def test_the_cors_preflight_allows_the_demo_visitor_header():
    origin = (
        settings.cors_origins[0]
        if settings.cors_origins and settings.cors_origins != ["*"]
        else "http://localhost:5173"
    )
    response = TestClient(app).options(
        "/api/v2/demo/analyze",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "x-demo-visitor,x-api-key,idempotency-key,content-type",
        },
    )
    assert response.status_code == 200
    assert "x-demo-visitor" in response.headers["access-control-allow-headers"].lower()
