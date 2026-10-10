from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from tests.fakes.search_provider import InMemorySearchProvider

from app.search.evaluation import evaluate_run
from app.search.models import SearchDocument, SearchFilter, SearchIndexSpec, SearchRequest, SearchScope

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "search"


def _load(name: str):
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def _document(raw: dict) -> SearchDocument:
    metadata = {
        "status": raw["status"],
        "tags": raw["tags"],
    }
    return SearchDocument(
        document_id=raw["document_id"],
        tenant_id=raw["tenant_id"],
        source_type=raw["source_type"],
        source_id=raw["source_id"],
        provider=raw["provider"],
        title=raw["title"],
        text=raw["text"],
        metadata=metadata,
        acl_tokens=raw["acl_tokens"],
        source_uri=raw["source_uri"],
        updated_at=datetime.fromisoformat(raw["updated_at"].replace("Z", "+00:00")),
        content_version=raw["content_version"],
        permission_version="acl-v1",
    )


def _request(raw: dict) -> SearchRequest:
    return SearchRequest(
        text=raw["text"],
        scope=SearchScope(
            tenant_id=raw["tenant_id"],
            principal_id="golden-evaluator",
            purpose="golden_evaluation",
            acl_tokens=raw["acl_tokens"],
        ),
        filters=tuple(
            SearchFilter(field=field, value=value)
            for field, value in raw["filters"].items()
        ),
        limit=10,
        request_id=raw["query_id"],
    )


@pytest.mark.asyncio
async def test_fake_provider_runs_golden_corpus_and_emits_machine_readable_report():
    documents = _load("documents.json")
    queries = _load("queries.json")
    judgments = _load("judgments.json")
    provider = InMemorySearchProvider()

    await provider.connect()
    await provider.ensure_index(
        SearchIndexSpec(
            alias="support-search",
            generation="support-v1",
            schema_version="schema-v1",
            vector_dimensions=3,
            embedding_model_version="golden-v1",
        )
    )
    await provider.activate_alias("support-search", "support-v1")
    write_result = await provider.upsert([_document(document) for document in documents])
    assert write_result.attempted == len(documents)
    assert write_result.succeeded == len(documents)

    retrieved_by_query: dict[str, list[str]] = {}
    results_by_query: dict[str, tuple] = {}
    for query in queries:
        response = await provider.search(_request(query))
        retrieved_by_query[query["query_id"]] = [result.document_id for result in response.results]
        results_by_query[query["query_id"]] = response.results

    relevance_by_query: dict[str, dict[str, int]] = {}
    for judgment in judgments:
        relevance_by_query.setdefault(judgment["query_id"], {})[judgment["document_id"]] = judgment["grade"]

    metrics = evaluate_run(retrieved_by_query, relevance_by_query, k=10)
    report = {
        "query_count": metrics.query_count,
        "mean_recall_at_k": round(metrics.mean_recall_at_k, 6),
        "mean_reciprocal_rank": round(metrics.mean_reciprocal_rank, 6),
        "mean_ndcg_at_k": round(metrics.mean_ndcg_at_k, 6),
        "retrieved_by_query": retrieved_by_query,
        "index_generation": "support-v1",
    }
    serialized = json.dumps(report, sort_keys=True)
    assert json.loads(serialized) == report
    assert report["query_count"] == len(relevance_by_query)

    hidden_results = results_by_query["q-acme-finance-hidden"]
    cross_tenant_results = results_by_query["q-zen-cross-tenant-id"]
    assert all(result.document_id != "acme-ticket-1004" for result in hidden_results)
    assert all(result.tenant_id == "tenant-zen" for result in cross_tenant_results)


@pytest.mark.asyncio
async def test_fake_provider_golden_report_is_repeatable():
    documents = _load("documents.json")
    queries = _load("queries.json")
    provider = InMemorySearchProvider()
    await provider.ensure_index(
        SearchIndexSpec(
            alias="support-search",
            generation="support-v1",
            schema_version="schema-v1",
            vector_dimensions=3,
            embedding_model_version="golden-v1",
        )
    )
    await provider.activate_alias("support-search", "support-v1")
    await provider.upsert([_document(document) for document in documents])

    first = [
        [result.document_id for result in (await provider.search(_request(query))).results]
        for query in queries
    ]
    second = [
        [result.document_id for result in (await provider.search(_request(query))).results]
        for query in queries
    ]
    assert first == second
