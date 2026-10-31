"""The deployed entry point serves the mounted routes over the seeded fictional catalog."""

from fastapi.testclient import TestClient

from app.demo_data import DEMO_SEED, load_demo_catalog
from app.main import API_PREFIX, create_app


def _context(**overrides):
    base = {
        "tenant_id": "tenant-01",
        "principal_id": "user-0001",
        "request_id": "request-wiring-001",
        "purpose": "search",
        "locale": "en-US",
        "device": "web",
        "age": 16,
    }
    return {**base, **overrides}


def test_health_and_mounted_search_return_demo_results() -> None:
    client = TestClient(create_app())

    assert client.get("/health").json() == {"service": "discovery-api", "status": "ok"}
    response = client.post(f"{API_PREFIX}/v1/search", json={"query": "adventure", "context": _context()})

    assert response.status_code == 200
    body = response.json()
    assert body["error"] is None
    assert body["total_matches"] >= 1
    assert all(item["experience_id"].startswith("exp-") for item in body["results"])


def test_home_feed_is_served_for_a_demo_user() -> None:
    client = TestClient(create_app())

    response = client.post(f"{API_PREFIX}/v1/home", json={"context": _context(purpose="home")})

    assert response.status_code == 200
    assert response.json()["results"]


def test_routes_exist_only_under_the_prefix() -> None:
    client = TestClient(create_app())

    assert client.post("/v1/search", json={"query": "adventure", "context": _context()}).status_code == 404


def test_the_web_clients_old_age_band_field_is_rejected() -> None:
    client = TestClient(create_app())
    context = {key: value for key, value in _context().items() if key != "age"} | {"age_band": "teen"}

    assert client.post(f"{API_PREFIX}/v1/search", json={"query": "adventure", "context": context}).status_code == 422


def test_unknown_tenant_gets_no_results() -> None:
    client = TestClient(create_app())

    response = client.post(
        f"{API_PREFIX}/v1/search",
        json={"query": "adventure", "context": _context(tenant_id="tenant-unknown")},
    )

    assert response.status_code == 200
    assert response.json()["results"] == []


def test_demo_catalog_is_deterministic_fictional_and_skips_unindexable_records() -> None:
    experiences, documents, users = load_demo_catalog()
    again = load_demo_catalog(DEMO_SEED)

    assert [d.experience_id for d in documents] == [d.experience_id for d in again[1]]
    assert 0 < len(documents) < len(experiences)
    assert all(d.synthetic for d in documents)
    assert all(user.synthetic for user in users)
