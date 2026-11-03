"""OpenSearch client, indexing, retrieval and service behavior against an in-process fake cluster."""

import json

import httpx
import pytest

from app.config import FeatureFlags
from app.demo_data import load_demo_catalog
from app.embedding import HASH_EMBEDDING_VERSION, HashingEmbedder
from app.opensearch.client import OpenSearchClient, OpenSearchError, OpenSearchUnavailable
from app.opensearch.index import (
    READ_ALIAS,
    WRITE_ALIAS,
    OpenSearchBulkProvider,
    bulk_requests,
    ensure_catalog_index,
    load_catalog,
)
from app.opensearch.retriever import OpenSearchRetriever
from app.opensearch.service import OpenSearchSearchService
from app.routes.search import LocalSearchService, SearchRequest
from app.search.mapping import CatalogMappingVersions
from packages.platform_contracts.discovery import DiscoveryRequestContext

EXPERIENCES, DOCUMENTS, USERS = load_demo_catalog()
VERSIONS = CatalogMappingVersions(embedding_model_version=HASH_EMBEDDING_VERSION)


class FakeCluster:
    """Records requests and answers like OpenSearch for the calls the adapter makes."""

    def __init__(self, *, hits=None, bulk_status=200, down=False):
        self.requests: list[httpx.Request] = []
        self.indexes: dict[str, dict] = {}
        self.hits = hits if hits is not None else []
        self.bulk_status = bulk_status
        self.down = down
        self.bulk_ids: list[str] = []

    def client(self, **kwargs) -> OpenSearchClient:
        return OpenSearchClient("https://search.test", transport=httpx.MockTransport(self.handle), **kwargs)

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.down:
            raise httpx.ConnectError("refused", request=request)
        path = request.url.path
        if request.method == "HEAD" and path.startswith("/_alias/"):
            alias = path.removeprefix("/_alias/")
            return httpx.Response(
                200 if any(alias in body.get("aliases", {}) for body in self.indexes.values()) else 404
            )
        if request.method == "HEAD":
            return httpx.Response(200 if path.lstrip("/") in self.indexes else 404)
        if request.method == "PUT":
            self.indexes[path.lstrip("/")] = json.loads(request.content)
            return httpx.Response(200, json={"acknowledged": True})
        if path == "/_bulk":
            lines = [json.loads(line) for line in request.content.decode().strip().split("\n")]
            actions = lines[0::2]
            self.bulk_ids += [a["index"]["_id"] for a in actions]
            return httpx.Response(200, json={"items": [{"index": {"status": self.bulk_status}} for _ in actions]})
        if path.endswith("/_refresh"):
            return httpx.Response(200, json={})
        if path.endswith("/_count"):
            return httpx.Response(200, json={"count": len(set(self.bulk_ids))})
        if path.endswith("/_search"):
            return httpx.Response(200, json={"hits": {"hits": self.hits}})
        return httpx.Response(404)

    def search_bodies(self):
        return [json.loads(r.content) for r in self.requests if r.url.path.endswith("/_search")]


def _hit(document, score, names=("title_term",)):
    source = document.model_dump(mode="json")
    source.pop("embedding")
    return {"_source": source, "_score": score, "matched_queries": list(names)}


def _request(query="workshop", **context):
    base = {
        "tenant_id": "tenant-01",
        "principal_id": "user-0003",
        "request_id": "request-os-001",
        "purpose": "search",
        "locale": "en-US",
        "device": "web",
        "age": 16,
    }
    return SearchRequest(query=query, context=DiscoveryRequestContext(**{**base, **context}))


def _titled(fragment):
    """Documents matching the fragment that the request's user is eligible to see (per the in-memory service)."""
    eligible = {r.experience_id for r in LocalSearchService(DOCUMENTS, USERS).search(_request(fragment)).results}
    return [d for d in DOCUMENTS if d.experience_id in eligible]


def _user():
    return next(u for u in USERS if u.user_id == "user-0003")


# ---- client ----


def test_client_never_exposes_credentials() -> None:
    client = OpenSearchClient("https://search.test", username="admin", password="hunter2-secret")

    assert "hunter2" not in repr(client)
    assert "admin" not in repr(client)


def test_unreachable_cluster_and_server_errors_are_reported_as_unavailable() -> None:
    with pytest.raises(OpenSearchUnavailable) as caught:
        FakeCluster(down=True).client().health()
    assert "refused" not in str(caught.value)

    unavailable = OpenSearchClient("https://search.test", transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    with pytest.raises(OpenSearchUnavailable):
        unavailable.count("x")


def test_rejected_requests_raise_a_non_unavailable_error() -> None:
    client = OpenSearchClient(
        "https://search.test", transport=httpx.MockTransport(lambda r: httpx.Response(400, json={}))
    )
    with pytest.raises(OpenSearchError) as caught:
        client.search("x", {})
    assert not isinstance(caught.value, OpenSearchUnavailable)


# ---- index and ingest ----


def test_index_is_created_once_with_strict_mapping_aliases_and_meta() -> None:
    cluster = FakeCluster()
    client = cluster.client()

    name = ensure_catalog_index(client, VERSIONS)
    ensure_catalog_index(client, VERSIONS)

    body = cluster.indexes[name]
    assert name == VERSIONS.index_name
    assert body["mappings"]["dynamic"] == "strict"
    assert body["mappings"]["_meta"]["embedding_model_version"] == HASH_EMBEDDING_VERSION
    assert set(body["aliases"]) == {READ_ALIAS, WRITE_ALIAS}
    assert len([r for r in cluster.requests if r.method == "PUT"]) == 1


def test_a_later_generation_is_created_without_aliases_until_swapped() -> None:
    cluster = FakeCluster()
    client = cluster.client()
    first = ensure_catalog_index(client, VERSIONS)
    second = ensure_catalog_index(
        client, CatalogMappingVersions(embedding_model_version=HASH_EMBEDDING_VERSION, generation="2")
    )

    assert "aliases" in cluster.indexes[first]
    assert "aliases" not in cluster.indexes[second]


def test_load_catalog_indexes_every_document_by_stable_id_and_is_idempotent() -> None:
    cluster = FakeCluster()
    client = cluster.client()

    first = load_catalog(client, DOCUMENTS, versions=VERSIONS)
    load_catalog(client, DOCUMENTS, versions=VERSIONS)

    assert first.accepted == len(DOCUMENTS) and first.quarantined == 0
    assert set(cluster.bulk_ids) == {d.exposure_key for d in DOCUMENTS}
    assert client.count(VERSIONS.index_name) == len(DOCUMENTS)


@pytest.mark.parametrize(
    ("status", "bucket"), [(201, "accepted_ids"), (429, "transient_ids"), (503, "transient_ids"), (400, "failed_ids")]
)
def test_bulk_statuses_map_to_worker_partitions(status, bucket) -> None:
    result = OpenSearchBulkProvider(FakeCluster(bulk_status=status).client()).bulk_upsert(bulk_requests(DOCUMENTS[:2]))

    assert len(getattr(result, bucket)) == 2


def test_unreachable_cluster_during_bulk_is_transient_so_the_worker_quarantines_after_retries() -> None:
    provider = OpenSearchBulkProvider(FakeCluster(down=True).client())
    result = provider.bulk_upsert(bulk_requests(DOCUMENTS[:2]))

    assert len(result.transient_ids) == 2 and not result.accepted_ids


# ---- retrieval ----


def test_lexical_query_applies_hard_filters_and_names_clauses() -> None:
    cluster = FakeCluster(hits=[_hit(_titled("workshop")[0], 7.5)])
    OpenSearchRetriever(cluster.client()).lexical("workshop", _context(), _user())

    body = cluster.search_bodies()[0]
    filters = body["query"]["bool"]["filter"]
    assert {"term": {"tenant_id": "tenant-01"}} in filters
    assert {"term": {"blocked": False}} in filters
    assert {"term": {"safety_state": "approved"}} in filters
    assert {"term": {"availability": "available"}} in filters
    assert body["_source"] == {"excludes": ["embedding"]}
    names = set()
    for clause in body["query"]["bool"]["should"]:
        spec = next(iter(clause.values()))
        names.add(spec.get("_name") or next(v for v in spec.values() if isinstance(v, dict))["_name"])
    assert {"exact_id", "title_phrase", "title_term", "description_term"} <= names


def test_lexical_results_carry_scores_reasons_and_titles() -> None:
    docs = _titled("workshop")[:2]
    cluster = FakeCluster(hits=[_hit(docs[0], 10.0, ("title_phrase", "title_term")), _hit(docs[1], 5.0)])

    result, titles = OpenSearchRetriever(cluster.client()).lexical("workshop", _context(), _user())

    ids = [c.experience_id for c in result.source_result.candidates]
    assert ids == [d.experience_id for d in docs]
    assert result.source_result.candidates[0].score == 1.0
    assert result.evidence[0].matched_fields == ("title",)
    assert result.evidence[0].phrase_match is True
    assert titles[docs[0].experience_id] == docs[0].title


def test_documents_failing_python_eligibility_are_dropped_even_if_the_index_returns_them() -> None:
    doc = _titled("workshop")[0]
    leaked = doc.model_copy(update={"blocked": True})
    cluster = FakeCluster(hits=[_hit(leaked, 9.0)])

    result, _ = OpenSearchRetriever(cluster.client()).lexical("workshop", _context(), _user())

    assert result.source_result.candidates == ()


def test_vector_query_filters_inside_the_knn_request_and_inverts_lucene_scores() -> None:
    doc = _titled("workshop")[0]
    cluster = FakeCluster(hits=[_hit(doc, 0.9, ())])
    embedder = HashingEmbedder()
    from app.search.vector import VectorQuery

    query = VectorQuery(
        embedding=embedder.embed("workshop"), embedding_model_version=embedder.model_version, dimensions=384
    )
    result, _ = OpenSearchRetriever(cluster.client()).vector(query, _context(), _user(), k=5)

    knn = cluster.search_bodies()[0]["query"]["knn"]["embedding"]
    assert {"term": {"tenant_id": "tenant-01"}} in knn["filter"]["bool"]["filter"]
    assert len(knn["vector"]) == 384
    assert result.evidence[0].cosine_similarity == pytest.approx(0.8)
    assert result.source_result.candidates[0].score == pytest.approx(0.9)


# ---- service ----


def _context():
    from app.domain.models import ImmersiveDiscoveryContext

    return ImmersiveDiscoveryContext(request_context=_request().context, surface="search")


def _service(cluster, **flags):
    return OpenSearchSearchService(
        OpenSearchRetriever(cluster.client()),
        DOCUMENTS,
        USERS,
        embedder=HashingEmbedder(),
        features=FeatureFlags(**flags),
    )


def test_service_ranks_with_cluster_results_when_available() -> None:
    docs = _titled("workshop")[:2]
    response = _service(FakeCluster(hits=[_hit(docs[0], 8.0), _hit(docs[1], 4.0)])).search(_request())

    assert response.error is None and response.fallback is False
    assert [r.experience_id for r in response.results] == [d.experience_id for d in docs]
    assert response.results[0].title == docs[0].title


def test_service_falls_back_to_the_in_memory_catalog_when_the_cluster_is_down() -> None:
    response = _service(FakeCluster(down=True)).search(_request())
    local = LocalSearchService(DOCUMENTS, USERS).search(_request())

    assert response.error is None and response.fallback is True
    assert [r.experience_id for r in response.results] == [r.experience_id for r in local.results]


def test_service_runs_hybrid_through_both_sources() -> None:
    docs = _titled("workshop")[:2]
    cluster = FakeCluster(hits=[_hit(docs[0], 0.95, ("title_term",)), _hit(docs[1], 0.9, ("title_term",))])

    response = _service(cluster, vector=True, hybrid=True).search(_request())

    bodies = cluster.search_bodies()
    assert len(bodies) == 2 and "knn" in bodies[1]["query"]
    assert response.decision_trace is not None
    retrieval = next(s for s in response.decision_trace.stages if s.stage == "retrieval")
    assert set(retrieval.reason_codes) == {"lexical", "vector"}


# ---- in-memory vector and hybrid ----


def test_in_memory_vector_search_finds_overlapping_titles_and_drops_noise() -> None:
    service = LocalSearchService(
        DOCUMENTS, USERS, embedder=HashingEmbedder(), features=FeatureFlags(lexical=False, vector=True)
    )

    hit = service.search(_request("cloud workshop"))
    noise = service.search(_request("zzzz qqqq"))

    assert hit.results and "workshop" in hit.results[0].title.lower()
    assert hit.results[0].evidence == ("embedding",)
    assert noise.results == ()


def test_vector_disabled_by_default_keeps_lexical_only_behavior() -> None:
    default = LocalSearchService(DOCUMENTS, USERS, embedder=HashingEmbedder()).search(_request("cloud workshop"))
    plain = LocalSearchService(DOCUMENTS, USERS).search(_request("cloud workshop"))

    assert [r.experience_id for r in default.results] == [r.experience_id for r in plain.results]
