"""POST /api/discovery/v1/products/search against an in-process fake cluster (no network, no real data)."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.opensearch.client import OpenSearchClient
from app.opensearch.products import MAX_WINDOW, search_page
from app.routes import products

URL = "/api/discovery/v1/products/search"
DOCS = {
    f"P{i:02d}": {
        "title": f"running shoe {i}",
        "brand": "Acme" if i % 2 else "Zed",
        "color": "red",
        "bullets": "x" * 400 if i == 0 else f"bullet {i}",
        "description": "",
        "locale": "us" if i < 7 else "es",
    }
    for i in range(12)
}


class FakeCluster:
    def __init__(self, status: int = 200) -> None:
        self.bodies: list[dict] = []
        self.operators: list[str] = []
        self.status = status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if self.status != 200:
            return httpx.Response(self.status, json={})
        body = json.loads(request.content)
        self.bodies.append(body)
        query = body["query"]
        locale = None
        if "bool" in query:
            locale = query["bool"]["filter"][0]["term"]["locale"]
            query = query["bool"]["must"][0]
        words = set(query["multi_match"]["query"].lower().split())
        every = query["multi_match"]["operator"] == "and"
        self.operators.append(query["multi_match"]["operator"])
        matched = [
            (pid, doc)
            for pid, doc in sorted(DOCS.items())
            if (words <= set(doc["title"].split()) if every else words & set(doc["title"].split()))
            and (locale is None or doc["locale"] == locale)
        ]
        page = matched[body["from"] : body["from"] + body["size"]]
        hits = [
            {"_id": pid, "_score": 2.5, "_source": {k: v for k, v in doc.items() if k != "locale"}} for pid, doc in page
        ]
        return httpx.Response(200, json={"hits": {"total": {"value": len(matched)}, "hits": hits}})


@pytest.fixture
def cluster() -> FakeCluster:
    return FakeCluster()


@pytest.fixture
def client(cluster: FakeCluster):
    application = create_app()
    previous = products.service
    products.service = products.OpenSearchProductService(
        OpenSearchClient("http://fake:9200", transport=httpx.MockTransport(cluster))
    )
    yield TestClient(application)
    products.service = previous


def _post(client: TestClient, **body):
    return client.post(URL, json={"query": "shoe", **body})


def test_returns_ranked_results_with_display_fields(client: TestClient) -> None:
    data = _post(client, page_size=3).json()
    assert data["error"] is None and data["total_matches"] == 12
    assert [r["rank"] for r in data["results"]] == [1, 2, 3]
    first = data["results"][0]
    assert first["product_id"] == "P00" and first["brand"] == "Zed" and first["title"] == "running shoe 0"
    assert first["snippet"].endswith("…") and len(first["snippet"]) <= 240


def test_pages_continue_the_rank_and_do_not_overlap(client: TestClient) -> None:
    one = _post(client, page=1, page_size=5).json()["results"]
    two = _post(client, page=2, page_size=5).json()["results"]
    assert [r["rank"] for r in two] == [6, 7, 8, 9, 10]
    assert not {r["product_id"] for r in one} & {r["product_id"] for r in two}


def test_locale_filters_and_counts_only_that_locale(client: TestClient, cluster: FakeCluster) -> None:
    data = _post(client, locale="es", page_size=50).json()
    assert data["total_matches"] == 5 and all(r["product_id"] >= "P07" for r in data["results"])
    assert cluster.bodies[-1]["query"]["bool"]["filter"] == [{"term": {"locale": "es"}}]


def test_no_match_is_an_empty_page_not_an_error(client: TestClient) -> None:
    data = _post(client, query="zzz").json()
    assert data["results"] == [] and data["total_matches"] == 0 and data["error"] is None


@pytest.mark.parametrize(
    "body",
    [
        {"query": ""},
        {"query": "x" * 257},
        {"page": 0},
        {"page_size": 51},
        {"locale": "en US"},
        {"tenant_id": "tenant-01"},  # identity is never accepted from the body
    ],
)
def test_invalid_requests_are_rejected(client: TestClient, body: dict) -> None:
    assert client.post(URL, json={"query": "shoe", **body}).status_code == 422


def test_blank_query_returns_a_typed_error_without_calling_the_cluster(
    client: TestClient, cluster: FakeCluster
) -> None:
    data = client.post(URL, json={"query": "   "}).json()
    assert data["error"]["code"] == "invalid_query" and data["results"] == [] and cluster.bodies == []


def test_cluster_failure_fails_closed_with_no_detail(cluster: FakeCluster) -> None:
    application = create_app()
    failing = FakeCluster(status=500)
    products.service = products.OpenSearchProductService(
        OpenSearchClient("http://fake:9200", transport=httpx.MockTransport(failing))
    )
    try:
        data = _post(TestClient(application)).json()
    finally:
        products.service = products.UnconfiguredProductService()
    assert data["error"]["code"] == "search_unavailable" and data["results"] == []
    assert "500" not in json.dumps(data) and "fake" not in json.dumps(data)


def test_without_the_opensearch_backend_the_route_says_so() -> None:
    data = _post(TestClient(create_app())).json()
    assert data["error"]["code"] == "not_configured" and data["results"] == []


def test_paging_beyond_the_window_returns_nothing_without_a_request(cluster: FakeCluster) -> None:
    client = OpenSearchClient("http://fake:9200", transport=httpx.MockTransport(cluster))
    page = search_page(client, "shoe", page=MAX_WINDOW, page_size=10)
    assert page.total == 0 and page.hits == () and cluster.bodies == []


def test_route_requires_a_token_when_auth_is_on() -> None:
    application = create_app()

    class Refuse:
        def verify(self, token: str):  # pragma: no cover - never reached without a header
            raise AssertionError("no token was sent")

    application.state.auth_verifier = Refuse()
    assert TestClient(application).post(URL, json={"query": "shoe"}).status_code == 401


def test_every_word_must_match_and_widening_happens_only_when_nothing_does(
    client: TestClient, cluster: FakeCluster
) -> None:
    strict = _post(client, query="running shoe 3").json()
    assert strict["match"] == "all" and [r["product_id"] for r in strict["results"]] == ["P03"]
    assert cluster.operators == ["and"]

    cluster.operators.clear()
    wide = _post(client, query="shoe purple").json()
    assert wide["match"] == "any" and wide["total_matches"] == 12 and cluster.operators == ["and", "or"]


def test_a_single_word_never_widens(client: TestClient, cluster: FakeCluster) -> None:
    assert _post(client, query="purple").json()["total_matches"] == 0
    assert cluster.operators == ["and"]
