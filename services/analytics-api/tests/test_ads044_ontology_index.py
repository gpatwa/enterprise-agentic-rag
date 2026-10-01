# ruff: noqa: F811  (the shared `env` fixture is imported, then requested by name)
"""ADS-044: ontology nodes are indexed with the published snapshot and searched by scope."""

from __future__ import annotations

import json as jsonlib

from test_ads044_context_refresh import _ontology, env  # noqa: F401  (env is a fixture)

from app.context import OntologyFileRefreshSource, OpenSearchContextIndex


class _Response:
    def __init__(self, payload=None, status_code=200):
        self.payload, self.status_code = payload or {}, status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeOpenSearch:
    """In-memory index that really evaluates bool/term/terms/must_not/multi_match."""

    def __init__(self, *, exists=False, leaky=False):
        self.exists, self.leaky = exists, leaky
        self.docs: dict[str, dict] = {}
        self.puts: list[tuple[str, dict]] = []

    def head(self, url):
        return _Response(status_code=200 if self.exists else 404)

    def put(self, url, *, json):
        self.puts.append((url, json))
        return _Response({"acknowledged": True})

    def post(self, url, *, json=None, content=None, headers=None):
        if url.endswith("/_bulk"):
            lines = [line for line in content.split("\n") if line]
            for action, source in zip(lines[::2], lines[1::2], strict=True):
                self.docs[jsonlib.loads(action)["index"]["_id"]] = jsonlib.loads(source)
            return _Response({"errors": False})
        query = json["query"]["bool"]
        words = query["must"][0]["multi_match"]["query"].lower().split()
        hits = []
        for doc_id, doc in self.docs.items():
            if not self.leaky and not all(self._term(clause, doc) for clause in query["filter"]):
                continue
            if not self.leaky and any(self._term(clause, doc) for clause in query.get("must_not", [])):
                continue
            haystack = f"{doc['text']} {doc.get('label', '')} {doc['asset_id']}".lower()
            if any(word in haystack for word in words):
                hits.append({"_id": doc_id, "_score": 1.0, "_source": doc})
        return _Response({"hits": {"hits": hits}})

    @staticmethod
    def _term(clause, doc):
        if "term" in clause:
            ((field, value),) = clause["term"].items()
            return doc.get(field) == value
        ((field, values),) = clause["terms"].items()
        return doc.get(field) in values


def _published(env, tmp_path, **ontology_kwargs):
    warehouse, clock, registry, published, make = env
    worker = make(
        ontology_source=OntologyFileRefreshSource(_ontology(tmp_path, **ontology_kwargs), tenant_id="tenant-a")
    )
    snapshot_id = worker.run_once().snapshot_id
    return registry.get(snapshot_id, "tenant-a")


def test_index_snapshot_adds_ontology_documents_with_lifecycle_and_aliases(env, tmp_path):
    snapshot = _published(env, tmp_path, lifecycle="candidate")
    client = FakeOpenSearch()
    index = OpenSearchContextIndex("http://os", "ctx", client)
    assert index.index_snapshot(snapshot) == len(snapshot.metadata_assets) + 2
    revenue = client.docs[f"tenant-a:{snapshot.snapshot_id}:ontology_node:revenue"]
    assert revenue["doc_type"] == "ontology_node" and revenue["node_type"] == "metric"
    assert revenue["lifecycle"] == "candidate" and revenue["certified"] is False  # never promoted
    assert "sales" in revenue["text"]
    assert client.docs[f"tenant-a:{snapshot.snapshot_id}:ontology_node:orders"]["certified"] is True


def test_asset_search_never_returns_ontology_documents(env, tmp_path):
    snapshot = _published(env, tmp_path)
    client = FakeOpenSearch()
    index = OpenSearchContextIndex("http://os", "ctx", client)
    index.index_snapshot(snapshot)
    results = index.search("revenue sales orders customers payments", tenant_id="tenant-a", certified_only=False)
    assert results and all(not item.asset_id == "revenue" for item in results)
    assert not any("ontology" in item.citation for item in results)
    leaky = FakeOpenSearch(leaky=True)
    leaky.docs = client.docs
    leaked = OpenSearchContextIndex("http://os", "ctx", leaky).search(
        "revenue", tenant_id="tenant-a", certified_only=False
    )
    assert all(item.asset_id != "revenue" for item in leaked)  # filtered again on the client side


def test_ontology_search_is_scoped_certified_and_alias_aware(env, tmp_path):
    snapshot = _published(env, tmp_path, extra_node=True)
    client = FakeOpenSearch()
    index = OpenSearchContextIndex("http://os", "ctx", client)
    index.index_snapshot(snapshot)
    scope = {"tenant_id": "tenant-a", "snapshot_id": snapshot.snapshot_id}
    (hit,) = index.search_ontology("sales", **scope)
    assert (hit.node_id, hit.node_type, hit.lifecycle) == ("revenue", "metric", "certified")
    assert hit.citation == f"context:{snapshot.snapshot_id}:ontology:revenue"
    assert index.search_ontology("refunds", **scope) == ()  # candidate hidden by default
    (candidate,) = index.search_ontology("refunds", certified_only=False, **scope)
    assert candidate.lifecycle == "candidate"
    assert {h.node_id for h in index.search_ontology("revenue orders", node_types=("dataset",), **scope)} == {"orders"}
    assert index.search_ontology("sales", tenant_id="tenant-b", snapshot_id=snapshot.snapshot_id) == ()
    assert index.search_ontology("sales", tenant_id="tenant-a", snapshot_id="refresh:tenant-a:other") == ()


def test_ontology_search_rechecks_scope_when_the_server_leaks(env, tmp_path):
    snapshot = _published(env, tmp_path, extra_node=True)
    client = FakeOpenSearch(leaky=True)
    index = OpenSearchContextIndex("http://os", "ctx", client)
    index.index_snapshot(snapshot)
    client.docs["tenant-b:x:ontology_node:revenue"] = {
        **client.docs[f"tenant-a:{snapshot.snapshot_id}:ontology_node:revenue"],
        "tenant_id": "tenant-b",
    }
    hits = index.search_ontology("revenue refunds", tenant_id="tenant-a", snapshot_id=snapshot.snapshot_id)
    assert {h.node_id for h in hits} == {"revenue"}  # tenant-b copy and candidate "refunds" dropped


def test_existing_index_gains_ontology_mapping_additively():
    client = FakeOpenSearch(exists=True)
    OpenSearchContextIndex("http://os", "ctx", client).ensure_index()
    url, body = client.puts[0]
    assert url == "http://os/ctx/_mapping"
    assert body["properties"]["doc_type"] == {"type": "keyword"}


def test_refresh_worker_publish_hook_indexes_ontology_end_to_end(env, tmp_path):
    warehouse, clock, registry, published, make = env
    client = FakeOpenSearch()
    index = OpenSearchContextIndex("http://os", "ctx", client)
    worker = make(
        on_publish=index.index_snapshot,
        ontology_source=OntologyFileRefreshSource(_ontology(tmp_path), tenant_id="tenant-a"),
    )
    snapshot_id = worker.run_once().snapshot_id
    (hit,) = index.search_ontology("sales", tenant_id="tenant-a", snapshot_id=snapshot_id)
    assert hit.node_id == "revenue"
    assert hit.citation.startswith("context:refresh:")
