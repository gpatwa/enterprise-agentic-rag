"""RO-6: compare Qdrant vector search with OpenSearch lexical, vector and hybrid on the search golden corpus.

Same documents, same embeddings, same judgments, same evaluator (``app.search.evaluation``). Only IDs and metrics are
written to the report, never document text or embeddings. Spend: one Azure OpenAI embeddings call per uncached text
(about 36 short texts for the committed fixtures); embeddings are cached in ``--cache`` so a re-run costs nothing.

    AZURE_OPENAI_ENDPOINT=https://<acct>.openai.azure.com AZURE_OPENAI_DEPLOYMENT=text-embedding-3-small \
    AZURE_OPENAI_API_KEY=... python scripts/compare_search_backends.py \
        --opensearch-url http://localhost:9200 --qdrant-url http://localhost:6333 --out report.json --cache cache.json
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

DIMENSIONS = 1536
FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "search"


def _embed(texts: list[str], cache_path: Path | None) -> dict[str, list[float]]:
    import httpx

    cache: dict[str, list[float]] = json.loads(cache_path.read_text()) if cache_path and cache_path.exists() else {}
    missing = [t for t in dict.fromkeys(texts) if t not in cache]
    if missing:
        endpoint, deployment, key = (
            os.environ.get(n) for n in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT", "AZURE_OPENAI_API_KEY")
        )
        if not (endpoint and deployment and key):
            sys.exit(
                "AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_DEPLOYMENT and AZURE_OPENAI_API_KEY are required for uncached texts"
            )
        for start in range(0, len(missing), 16):
            batch = missing[start : start + 16]
            response = httpx.post(
                f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/embeddings?api-version=2024-10-21",
                headers={"api-key": key},
                json={"input": batch},
                timeout=60,
            )
            if response.status_code != 200:  # status only: never echo a body that could carry request details
                sys.exit(f"embedding request failed (HTTP {response.status_code})")
            for text, item in zip(batch, sorted(response.json()["data"], key=lambda d: d["index"])):
                cache[text] = item["embedding"]
        if cache_path:
            cache_path.write_text(json.dumps(cache))
    return cache


def _visible(doc: dict, tenant: str, tokens: list[str]) -> bool:
    """The same rule as ``app.search.opensearch._source_is_visible``."""
    doc_tokens = set(doc["acl_tokens"])
    if doc["tenant_id"] != tenant or f"tenant:{tenant}" not in doc_tokens:
        return False
    doc_groups = {t for t in doc_tokens if not t.startswith("tenant:")}
    scope_groups = {t for t in tokens if not t.startswith("tenant:")}
    return not doc_groups or bool(doc_groups & scope_groups)


def _qdrant_run(
    url: str, docs: list[dict], queries: list[dict], vectors: dict[str, list[float]], k: int
) -> dict[str, list[str]]:
    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    client = QdrantClient(url=url)
    name = f"cmp-{uuid.uuid4().hex[:8]}"
    client.create_collection(name, vectors_config=qm.VectorParams(size=DIMENSIONS, distance=qm.Distance.COSINE))
    try:
        client.upsert(
            name,
            points=[
                qm.PointStruct(
                    id=i,
                    vector=vectors[f"{d['title']}\n{d['text']}"],
                    payload={k_: d[k_] for k_ in ("document_id", "tenant_id", "source_type", "status")},
                )
                for i, d in enumerate(docs)
            ],
            wait=True,
        )
        by_id = {d["document_id"]: d for d in docs}
        out: dict[str, list[str]] = {}
        for q in queries:
            must = [qm.FieldCondition(key="tenant_id", match=qm.MatchValue(value=q["tenant_id"]))]
            for field, value in q["filters"].items():
                must.append(qm.FieldCondition(key=field, match=qm.MatchValue(value=value)))
            flt = qm.Filter(must=must)
            if hasattr(client, "query_points"):
                hits = client.query_points(name, query=vectors[q["text"]], query_filter=flt, limit=len(docs)).points
            else:  # older clients (the API pins 1.7.x)
                hits = client.search(name, query_vector=vectors[q["text"]], query_filter=flt, limit=len(docs))
            ids = [
                h.payload["document_id"]
                for h in hits
                if _visible(by_id[h.payload["document_id"]], q["tenant_id"], q["acl_tokens"])
            ]
            out[q["query_id"]] = ids[:k]
        return out
    finally:
        client.delete_collection(name)


def _opensearch_runs(url: str, docs: list[dict], queries: list[dict], vectors: dict[str, list[float]], k: int):
    os.environ.update(OPENSEARCH_ENABLED="true", OPENSEARCH_URL=url, OPENSEARCH_VECTOR_DIMENSIONS=str(DIMENSIONS))
    generation = f"cmp-{uuid.uuid4().hex[:8]}"
    os.environ["OPENSEARCH_INDEX_ALIAS"] = generation
    from app.config import Settings
    from app.search.models import FilterOperator, SearchFilter, SearchIndexSpec, SearchMode, SearchRequest, SearchScope
    from app.search.opensearch import OpenSearchProvider
    from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION, SupportSearchAttributes, SupportSearchDocument

    async def run():
        provider = OpenSearchProvider(config=Settings())
        await provider.connect()
        try:
            await provider.ensure_index(
                SearchIndexSpec(
                    alias=generation,
                    generation=generation,
                    schema_version=SUPPORT_SEARCH_SCHEMA_VERSION,
                    vector_dimensions=DIMENSIONS,
                    embedding_model_version="cmp",
                )
            )
            documents = [
                SupportSearchDocument(
                    document_id=d["document_id"],
                    tenant_id=d["tenant_id"],
                    source_type=d["source_type"],
                    source_id=d["source_id"],
                    provider=d["provider"],
                    title=d["title"],
                    text=d["text"],
                    acl_tokens=tuple(d["acl_tokens"]),
                    source_uri=d.get("source_uri"),
                    content_version=d["content_version"],
                    embedding_model_version="cmp",
                    attributes=SupportSearchAttributes(status=d.get("status"), tags=list(d.get("tags", []))),
                    content_hash=hashlib.sha256(f"{d['title']}\n{d['text']}".encode()).hexdigest(),
                    vector=tuple(vectors[f"{d['title']}\n{d['text']}"]),
                    updated_at=datetime.fromisoformat(d["updated_at"].replace("Z", "+00:00")),
                )
                for d in docs
            ]
            result = await provider.upsert(documents)
            if result.failed:
                sys.exit(f"{result.failed} fixture documents failed to index")
            await provider._client.indices.refresh(index=generation)
            runs: dict[str, dict[str, list[str]]] = {}
            for mode in (SearchMode.LEXICAL, SearchMode.VECTOR, SearchMode.HYBRID):
                per_query = {}
                for q in queries:
                    scope = SearchScope(
                        tenant_id=q["tenant_id"],
                        principal_id="cmp",
                        purpose="evaluation",
                        acl_tokens=tuple(q["acl_tokens"]),
                    )
                    response = await provider.search(
                        SearchRequest(
                            text=q["text"],
                            scope=scope,
                            mode=mode,
                            limit=k,
                            filters=tuple(
                                SearchFilter(field=f, operator=FilterOperator.EQ, value=v)
                                for f, v in q["filters"].items()
                            ),
                            query_vector=tuple(vectors[q["text"]]) if mode is not SearchMode.LEXICAL else None,
                        )
                    )
                    per_query[q["query_id"]] = [r.document_id for r in response.results]
                runs[mode.value] = per_query
            info = await provider._client.info()
            return runs, info["version"]["number"]
        finally:
            try:
                await provider._client.indices.delete(index=generation)
            finally:
                await provider.close()

    return asyncio.run(run())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--opensearch-url", required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--cache", type=Path)
    parser.add_argument("--k", type=int, default=10)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.search.evaluation import evaluate_query, evaluate_run

    docs = json.loads((FIXTURES / "documents.json").read_text())
    queries = json.loads((FIXTURES / "queries.json").read_text())
    relevance: dict[str, dict[str, int]] = {q["query_id"]: {} for q in queries}
    for j in json.loads((FIXTURES / "judgments.json").read_text()):
        relevance[j["query_id"]][j["document_id"]] = int(j["grade"])
    by_id = {d["document_id"]: d for d in docs}

    texts = [f"{d['title']}\n{d['text']}" for d in docs] + [q["text"] for q in queries]
    vectors = _embed(texts, args.cache)

    all_runs: list[dict[str, dict[str, list[str]]]] = []
    os_version = ""
    for _ in range(args.repeats):
        runs, os_version = _opensearch_runs(args.opensearch_url, docs, queries, vectors, args.k)
        runs["qdrant_vector"] = _qdrant_run(args.qdrant_url, docs, queries, vectors, args.k)
        all_runs.append(runs)

    report: dict = {
        "corpus": {"documents": len(docs), "queries": len(queries), "k": args.k, "minimum_grade": 1},
        "versions": {
            "opensearch": os_version,
            "embedding": "text-embedding-3-small (1536)",
            "qdrant_url": "local container",
        },
        "repeats": args.repeats,
        "consistent_across_repeats": all(run == all_runs[0] for run in all_runs),
        "systems": {},
    }
    scope = {q["query_id"]: q for q in queries}
    for system in all_runs[0]:
        retrieved = all_runs[0][system]
        summary = evaluate_run(retrieved, relevance, k=args.k)
        per_query = {
            qid: evaluate_query(qid, retrieved.get(qid, ()), relevance[qid], k=args.k).ndcg_at_k for qid in relevance
        }
        leaks = sum(
            1
            for qid, ids in retrieved.items()
            for i in ids
            if not _visible(by_id[i], scope[qid]["tenant_id"], scope[qid]["acl_tokens"])
        )
        duplicates = sum(len(ids) - len(set(ids)) for ids in retrieved.values())
        report["systems"][system] = {
            "recall_at_k": round(summary.mean_recall_at_k, 4),
            "mrr": round(summary.mean_reciprocal_rank, 4),
            "ndcg_at_k": round(summary.mean_ndcg_at_k, 4),
            "acl_leaks": leaks,
            "duplicate_ids": duplicates,
            "worst_queries": [
                {"query_id": q, "ndcg": round(v, 4)}
                for q, v in sorted(per_query.items(), key=lambda kv: (kv[1], kv[0]))[:3]
            ],
        }
    args.out.write_text(json.dumps(report, indent=2))
    print(
        json.dumps(
            {s: {k_: v for k_, v in m.items() if k_ != "worst_queries"} for s, m in report["systems"].items()}, indent=1
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
