"""Opt-in checks against a real OpenSearch node; skipped unless DISCOVERY_TEST_OPENSEARCH_URL is set.

Start one locally with ``docker compose --profile search up -d opensearch`` and run:
``DISCOVERY_TEST_OPENSEARCH_URL=http://localhost:9200 pytest tests/test_opensearch_integration.py``
"""

import os
import uuid

import pytest

from app.config import FeatureFlags
from app.demo_data import load_demo_catalog
from app.embedding import HASH_EMBEDDING_VERSION, HashingEmbedder
from app.opensearch.client import OpenSearchClient
from app.opensearch.index import load_catalog
from app.opensearch.retriever import OpenSearchRetriever
from app.opensearch.service import OpenSearchSearchService
from app.routes.search import LocalSearchService, SearchRequest
from app.search.mapping import CatalogMappingVersions
from packages.platform_contracts.discovery import DiscoveryRequestContext

URL = os.environ.get("DISCOVERY_TEST_OPENSEARCH_URL")
pytestmark = pytest.mark.skipif(not URL, reason="DISCOVERY_TEST_OPENSEARCH_URL is not set")

_EXPERIENCES, DOCUMENTS, USERS = load_demo_catalog()


def _request(query: str) -> SearchRequest:
    return SearchRequest(
        query=query,
        context=DiscoveryRequestContext(
            tenant_id="tenant-01",
            principal_id="user-0003",
            request_id="request-it-001",
            purpose="search",
            locale="en-US",
            device="web",
            age=16,
        ),
    )


@pytest.fixture(scope="module")
def cluster():
    client = OpenSearchClient(URL or "", timeout=30.0)
    # A unique generation keeps this run from touching the shared aliases' index.
    versions = CatalogMappingVersions(
        embedding_model_version=HASH_EMBEDDING_VERSION, generation=f"it-{uuid.uuid4().hex[:8]}"
    )
    evidence = load_catalog(client, DOCUMENTS, versions=versions)
    assert evidence.accepted == len(DOCUMENTS) and evidence.quarantined == 0
    yield client, versions
    client._request("DELETE", f"/{versions.index_name}")


def _service(client, versions, **flags):
    return OpenSearchSearchService(
        OpenSearchRetriever(client, index=versions.index_name),
        DOCUMENTS,
        USERS,
        embedder=HashingEmbedder(),
        features=FeatureFlags(**flags),
    )


def test_every_document_is_indexed(cluster) -> None:
    client, versions = cluster
    assert client.count(versions.index_name) == len(DOCUMENTS)


def test_real_lexical_search_finds_the_expected_title_without_falling_back(cluster) -> None:
    client, versions = cluster
    response = _service(client, versions).search(_request("workshop"))

    assert response.error is None and response.fallback is False
    assert response.results and all("workshop" in r.title.lower() for r in response.results[:2])


def test_real_vector_search_finds_overlapping_titles(cluster) -> None:
    client, versions = cluster
    response = _service(client, versions, lexical=False, vector=True).search(_request("cloud workshop"))

    assert response.fallback is False
    assert response.results and "workshop" in response.results[0].title.lower()


def test_cluster_and_in_memory_agree_on_the_top_lexical_result(cluster) -> None:
    client, versions = cluster
    remote = _service(client, versions).search(_request("workshop"))
    local = LocalSearchService(DOCUMENTS, USERS).search(_request("workshop"))

    assert remote.results[0].experience_id == local.results[0].experience_id


def test_real_hybrid_search_does_not_fall_back_and_keeps_the_lexical_leader(cluster) -> None:
    client, versions = cluster
    hybrid = _service(client, versions, lexical=True, vector=True, hybrid=True).search(_request("cloud workshop"))
    lexical = _service(client, versions).search(_request("cloud workshop"))

    assert hybrid.error is None and hybrid.fallback is False and hybrid.results
    assert lexical.results[0].experience_id in [r.experience_id for r in hybrid.results[:5]]


def test_index_rebuilds_identically_after_it_is_lost() -> None:
    client = OpenSearchClient(URL or "", timeout=30.0)
    versions = CatalogMappingVersions(
        embedding_model_version=HASH_EMBEDDING_VERSION, generation=f"it-rebuild-{uuid.uuid4().hex[:8]}"
    )
    try:
        load_catalog(client, DOCUMENTS, versions=versions)
        before = _service(client, versions).search(_request("workshop"))
        count_before = client.count(versions.index_name)

        client._request("DELETE", f"/{versions.index_name}")
        assert not client.index_exists(versions.index_name)

        evidence = load_catalog(client, DOCUMENTS, versions=versions)
        after = _service(client, versions).search(_request("workshop"))

        assert evidence.accepted == len(DOCUMENTS) and client.count(versions.index_name) == count_before
        assert [r.experience_id for r in after.results] == [r.experience_id for r in before.results]
    finally:
        client._request("DELETE", f"/{versions.index_name}")
