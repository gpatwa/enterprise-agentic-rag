import sys

from fastapi.testclient import TestClient

from app.main import app


def test_health_is_deterministic_and_local() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"service": "discovery-api", "status": "ok"}


def test_service_does_not_import_support_or_analytics_products() -> None:
    imported_products = tuple(
        name
        for name in sys.modules
        if name.startswith("services.api") or name.startswith("services.analytics_api")
    )

    assert imported_products == ()
