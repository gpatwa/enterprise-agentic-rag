"""Public demo mode: it must stay off by default, build its own identity, and be tightly limited."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api_v2 import V2Runtime
from app.config import Settings
from app.demo import DEMO_PURPOSE, DemoLimiter, build_demo_router, client_address, demo_identity
from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse

VISITOR = "visitor-1234567890abcdef"


class FakeService:
    def __init__(self):
        self.calls = []

    def analyze(self, identity, *, purpose, idempotency_key, request_text):
        self.calls.append(("analyze", identity, purpose, request_text))
        return AnalyzeRunResponse(run_id="r1", state="running")

    def status(self, identity, *, purpose, run_id):
        self.calls.append(("status", identity, purpose, run_id))
        return AnalyzeRunResponse(run_id=run_id, state="running")

    def clarify(self, identity, *, purpose, run_id, ambiguity_code, selected_id):
        self.calls.append(("clarify", identity, purpose, run_id))
        return AnalyzeRunResponse(run_id=run_id, state="running")


def _client(enabled=True, per_address=3, global_daily=100, clock=None, service="fake"):
    settings = Settings(
        ANALYTICS_DEMO_ENABLED=enabled,
        ANALYTICS_DEMO_TENANT="tenant-demo",
        ANALYTICS_DEMO_PER_ADDRESS_HOURLY=per_address,
        ANALYTICS_DEMO_GLOBAL_DAILY=global_daily,
    )
    fake = FakeService() if service == "fake" else None
    runtime = V2Runtime(service=fake)
    limiter = DemoLimiter(per_address, global_daily, clock=clock or (lambda: 1000.0))
    app = FastAPI()
    app.include_router(build_demo_router(runtime, lambda: None, settings, limiter))
    return TestClient(app), fake


def _ask(client, text="revenue by month", visitor=VISITOR, address="203.0.113.7"):
    headers = {"X-Forwarded-For": address, "Idempotency-Key": "demo-key-0001"}
    if visitor:
        headers["X-Demo-Visitor"] = visitor
    return client.post("/api/v2/demo/analyze", json={"request_text": text}, headers=headers)


def test_demo_is_off_by_default():
    assert Settings().ANALYTICS_DEMO_ENABLED is False
    client, fake = _client(enabled=False)
    assert _ask(client).status_code == 404 and fake.calls == []
    assert client.get("/api/v2/demo/status").json() == {"enabled": False}


def test_the_identity_is_built_by_the_server_and_can_never_review():
    client, fake = _client()
    assert _ask(client).status_code == 202
    _, identity, purpose, _ = fake.calls[0]
    assert identity.tenant_id == "tenant-demo" and purpose == DEMO_PURPOSE
    assert identity.groups == [] and identity.purposes == [DEMO_PURPOSE]
    assert identity.user_id.startswith("demo:") and VISITOR not in identity.user_id  # the raw visitor id is not stored


def test_a_visitor_id_is_required_and_validated():
    client, fake = _client()
    assert _ask(client, visitor=None).status_code == 400
    assert _ask(client, visitor="short").status_code == 400
    assert _ask(client, visitor="../../etc/passwd/xxxxxxxx").status_code == 400
    assert fake.calls == []


def test_no_review_feedback_or_brief_routes_exist_for_the_demo():
    client, _ = _client()
    for method, path in (
        ("post", "/api/v2/demo/runs/r1/review"),
        ("post", "/api/v2/demo/runs/r1/feedback"),
        ("get", "/api/v2/demo/reviews/pending"),
        ("get", "/api/v2/demo/runs/r1/review-brief"),
    ):
        assert getattr(client, method)(path, headers={"X-Demo-Visitor": VISITOR}).status_code in (404, 405)


def test_questions_are_length_limited_and_the_body_is_strict():
    client, fake = _client()
    assert _ask(client, text="x" * 301).status_code == 422
    response = client.post(
        "/api/v2/demo/analyze",
        json={"request_text": "revenue", "purpose": "analytics-reviewer"},
        headers={"X-Demo-Visitor": VISITOR},
    )
    assert response.status_code == 422 and fake.calls == []  # the caller cannot choose a purpose


def test_per_address_and_daily_limits_apply_and_fail_closed():
    now = [1000.0]
    client, fake = _client(per_address=2, global_daily=3, clock=lambda: now[0])
    assert [_ask(client).status_code for _ in range(3)] == [202, 202, 429]
    assert _ask(client).json()["detail"] == "demo_rate_limited"
    assert _ask(client, address="198.51.100.9").status_code == 202  # another address, daily total now 3
    assert _ask(client, address="198.51.100.10").json()["detail"] == "demo_daily_limit"
    now[0] += 3601  # an hour later the address window clears, but the daily ceiling still holds
    assert _ask(client).json()["detail"] == "demo_daily_limit"
    now[0] += 86_400
    assert _ask(client).status_code == 202
    assert len([c for c in fake.calls if c[0] == "analyze"]) == 4


def test_a_forged_forwarded_header_cannot_dodge_the_limit():
    client, _ = _client(per_address=1)
    first = client.post(
        "/api/v2/demo/analyze",
        json={"request_text": "revenue by month"},
        headers={"X-Demo-Visitor": VISITOR, "X-Forwarded-For": "1.1.1.1, 203.0.113.7"},
    )
    second = client.post(
        "/api/v2/demo/analyze",
        json={"request_text": "revenue by month"},
        headers={"X-Demo-Visitor": VISITOR, "X-Forwarded-For": "2.2.2.2, 203.0.113.7"},
    )
    assert (first.status_code, second.status_code) == (202, 429)  # the ingress-added last hop is what counts


def test_client_address_uses_the_last_forwarded_hop():
    request = SimpleNamespace(
        headers={"x-forwarded-for": "9.9.9.9, 10.0.0.1"}, client=SimpleNamespace(host="127.0.0.1")
    )
    assert client_address(request) == "10.0.0.1"


def test_the_limiter_stops_tracking_rather_than_growing_without_bound(monkeypatch):
    import app.demo as demo

    monkeypatch.setattr(demo, "_MAX_TRACKED_ADDRESSES", 3)
    limiter = DemoLimiter(5, 1000, clock=lambda: 10.0)
    assert [limiter.admit(a) for a in ("a", "b", "c")] == [None, None, None]
    assert limiter.admit("d") == "demo_busy"


def test_demo_identity_rejects_bad_visitor_ids_directly():
    assert demo_identity("tenant-demo", VISITOR).tenant_id == "tenant-demo"


def test_the_demo_tenant_has_its_own_certified_contract_and_table():
    root = Settings().ANALYTICS_SEMANTIC_REGISTRY_PATH
    demo = json.load(open(f"{root}/contracts/sales-demo-v1.json"))
    core = json.load(open(f"{root}/contracts/sales-core-v1.json"))
    assert demo["lifecycle"] == "certified" and demo["contract"]["tenant_id"] == "tenant-demo"
    demo_tables = {d["physical_name"] for d in demo["contract"]["datasets"]}
    core_tables = {d["physical_name"] for d in core["contract"]["datasets"]}
    assert demo_tables == {"demo_sales_orders"} and not (demo_tables & core_tables)
    assert demo["contract"]["tenant_id"] != core["contract"]["tenant_id"]


def test_signed_in_users_must_never_map_to_the_demo_tenant():
    settings = Settings(ANALYTICS_TENANT_MAP=json.dumps({"entra-tenant": "tenant-demo"}))
    assert "tenant-demo" in settings.entra_tenant_targets()
