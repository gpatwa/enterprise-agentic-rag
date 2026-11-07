"""Product index loading, reconciliation and retrieval against an in-process fake cluster.

The opt-in test at the bottom runs the same flow against a real node when DISCOVERY_TEST_OPENSEARCH_URL is set.
"""

from __future__ import annotations

import csv
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from app.evaluation.product_search import EvalQuery, evaluate
from app.ingest import ProductProvenance, ProductRecord, ingest, write_subset
from app.opensearch.client import OpenSearchClient, OpenSearchError
from app.opensearch.products import (
    BATCH_SIZE,
    ProductRetriever,
    ensure_product_index,
    load_products,
    product_mapping,
    read_subset_records,
    reconcile,
    stream_subset_records,
)

NOW = datetime(2026, 11, 4, tzinfo=timezone.utc)
INDEX = "discovery-products-test"


class FakeCluster:
    """Answers the calls the product module makes; search ranks by shared query words in the title."""

    def __init__(self, *, bulk_status: int = 200) -> None:
        self.indexes: dict[str, dict[str, dict]] = {}
        self.created: list[tuple[str, dict]] = []
        self.bulk_calls: list[int] = []
        self.searches: list[dict] = []
        self.bulk_status = bulk_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "HEAD":
            return httpx.Response(200 if path.strip("/") in self.indexes else 404)
        if request.method == "PUT":
            name = path.strip("/")
            self.indexes[name] = {}
            self.created.append((name, json.loads(request.content)))
            return httpx.Response(200, json={"acknowledged": True})
        if path == "/_bulk":
            lines = request.content.decode().strip().split("\n")
            actions = [json.loads(line)["index"] for line in lines[0::2]]
            docs = [json.loads(line) for line in lines[1::2]]
            self.bulk_calls.append(len(actions))
            items = []
            for action, doc in zip(actions, docs):
                if self.bulk_status in (200, 201):
                    self.indexes[action["_index"]][action["_id"]] = doc
                items.append({"index": {"_id": action["_id"], "status": self.bulk_status}})
            return httpx.Response(200, json={"items": items})
        if path.endswith("/_refresh"):
            return httpx.Response(200, json={})
        if path.endswith("/_count"):
            return httpx.Response(200, json={"count": len(self.indexes.get(path.split("/")[1], {}))})
        if path.endswith("/_search"):
            body = json.loads(request.content)
            self.searches.append(body)
            words = set(body["query"]["multi_match"]["query"].lower().split())
            docs = self.indexes.get(path.split("/")[1], {})
            scored = sorted(
                ((len(words & set(doc["title"].lower().split())), pid) for pid, doc in docs.items()),
                key=lambda item: (-item[0], item[1]),
            )
            hits = [{"_id": pid} for score, pid in scored if score > 0][: body["size"]]
            return httpx.Response(200, json={"hits": {"hits": hits}})
        return httpx.Response(404)


def _client(cluster: FakeCluster) -> OpenSearchClient:
    return OpenSearchClient("http://fake:9200", transport=httpx.MockTransport(cluster))


def _records(n: int = 5) -> list[ProductRecord]:
    titles = ["red running shoes", "blue running shoes", "office chair", "wireless mouse", "water bottle"]
    return [ProductRecord(product_id=f"P{i}", locale="us", title=titles[i % len(titles)] + f" {i}") for i in range(n)]


def test_mapping_is_strict_and_keyed_by_product_id() -> None:
    mapping = product_mapping()["mappings"]
    assert mapping["dynamic"] == "strict"
    assert set(mapping["properties"]) == {"product_id", "locale", "title", "description", "bullets", "brand", "color"}


def test_ensure_creates_once() -> None:
    cluster = FakeCluster()
    client = _client(cluster)
    ensure_product_index(client, INDEX)
    ensure_product_index(client, INDEX)
    assert len(cluster.created) == 1 and cluster.created[0][0] == INDEX


def test_load_is_idempotent_and_reconciles() -> None:
    cluster = FakeCluster()
    client = _client(cluster)
    first = load_products(client, _records(5), INDEX)
    second = load_products(client, _records(5), INDEX)
    assert (first.received, first.accepted, first.failed) == (5, 5, ())
    assert second.accepted == 5
    result = reconcile(client, 5, INDEX)
    assert result.in_sync and result.indexed == 5
    assert not reconcile(client, 6, INDEX).in_sync


def test_load_batches_large_inputs() -> None:
    cluster = FakeCluster()
    load_products(_client(cluster), _records(BATCH_SIZE + 7), INDEX)
    assert cluster.bulk_calls == [BATCH_SIZE, 7]


def test_rejected_documents_are_reported_not_hidden() -> None:
    cluster = FakeCluster(bulk_status=400)
    evidence = load_products(_client(cluster), _records(3), INDEX)
    assert evidence.accepted == 0 and evidence.failed == ("P0", "P1", "P2")


def test_retriever_returns_ranked_ids_and_handles_empty_queries() -> None:
    cluster = FakeCluster()
    client = _client(cluster)
    load_products(client, _records(5), INDEX)
    retriever = ProductRetriever(client, INDEX)
    assert retriever("running shoes", 2) == ["P0", "P1"]
    assert retriever("   ", 5) == [] and retriever("shoes", 0) == []
    assert cluster.searches[0]["size"] == 2
    assert "title^3" in cluster.searches[0]["query"]["multi_match"]["fields"]


def test_retriever_plugs_into_the_evaluation_harness() -> None:
    cluster = FakeCluster()
    client = _client(cluster)
    load_products(client, _records(5), INDEX)
    queries = [EvalQuery("q1", "running shoes", {"P0": "E", "P1": "E", "P2": "I"})]
    report = evaluate(ProductRetriever(client, INDEX), queries, k=3, repeats=2)
    assert report["ndcg_at_k"]["mean"] == pytest.approx(1.0) and report["consistent_across_repeats"] is True


def test_search_failure_surfaces_instead_of_returning_empty() -> None:
    def broken(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    retriever = ProductRetriever(OpenSearchClient("http://fake:9200", transport=httpx.MockTransport(broken)), INDEX)
    with pytest.raises(OpenSearchError):
        retriever("shoes", 3)


def _built_subset(tmp_path: Path) -> Path:
    fields = ["product_id", "product_locale", "product_title"]
    with (tmp_path / "p.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i in range(6):
            writer.writerow({"product_id": f"P{i}", "product_locale": "us", "product_title": f"widget {i}"})
    with (tmp_path / "e.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["product_id", "product_locale", "small_version"])
        writer.writeheader()
        for i in range(6):
            writer.writerow({"product_id": f"P{i}", "product_locale": "us", "small_version": "1"})
    provenance = ProductProvenance(dataset="fixture", dataset_version="t", citation="synthetic", synthetic=True)
    out = tmp_path / "subset"
    write_subset(ingest(tmp_path / "p.csv", tmp_path / "e.csv", provenance=provenance, now=NOW), out)
    return out


def test_read_subset_verifies_before_returning(tmp_path: Path) -> None:
    out = _built_subset(tmp_path)
    records, expected = read_subset_records(out)
    assert len(records) == expected == 6
    path = out / "products.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n", encoding="utf-8")
    from app.ingest import IngestError

    with pytest.raises(IngestError, match="drift"):
        read_subset_records(out)


def test_stream_subset_records_is_lazy_and_verified_first(tmp_path: Path) -> None:
    out = _built_subset(tmp_path)
    records, expected = stream_subset_records(out)
    assert iter(records) is records and not isinstance(records, (list, tuple))  # one pass, nothing held in memory
    assert [r.product_id for r in records] == [r.product_id for r in read_subset_records(out)[0]]
    assert expected == 6
    path = out / "products.jsonl"
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n", encoding="utf-8")
    from app.ingest import IngestError

    with pytest.raises(IngestError, match="drift"):
        stream_subset_records(out)  # verification happens at the call, before any record is yielded


URL = os.environ.get("DISCOVERY_TEST_OPENSEARCH_URL")


@pytest.mark.skipif(not URL, reason="DISCOVERY_TEST_OPENSEARCH_URL is not set")
def test_real_node_load_reconcile_and_search(tmp_path: Path) -> None:
    client = OpenSearchClient(URL or "", timeout=30.0)
    index = f"discovery-products-it-{uuid.uuid4().hex[:8]}"
    records, expected = read_subset_records(_built_subset(tmp_path))
    try:
        evidence = load_products(client, records, index)
        assert evidence.failed == () and reconcile(client, expected, index).in_sync
        assert ProductRetriever(client, index)("widget 3", 3)[0] == "P3"
    finally:
        client._request("DELETE", f"/{index}")
