"""Lexical and vector retrieval over the OpenSearch catalog index.

OpenSearch applies coarse hard filters (tenant, not blocked, approved, available) and ranks. Every
returned document is then re-checked in Python by the same eligibility rules the in-memory
retrievers use, so the authoritative policy decision never depends on index contents alone.
"""

from __future__ import annotations

from typing import Any

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.domain.models import ImmersiveDiscoveryContext, UserProfile
from app.opensearch.client import OpenSearchClient
from app.opensearch.index import READ_ALIAS
from app.search.lexical import (
    LexicalEvidence,
    LexicalRetrievalResult,
    LexicalRetriever,
    _bounded_score,
    _normalize,
    _tokens,
)
from app.search.mapper import CatalogSearchDocument
from app.search.vector import VectorEvidence, VectorQuery, VectorRetrievalResult, VectorRetriever

_OVERFETCH = 5
_MAX_FETCH = 100
_FIELD_BY_CLAUSE = {
    "exact_id": "experience_id",
    "exact_creator": "creator_id",
    "title_phrase": "title",
    "title_term": "title",
    "tags_term": "tags",
    "description_term": "description",
}


def _hard_filters(tenant_id: str) -> list[dict[str, Any]]:
    return [
        {"term": {"tenant_id": tenant_id}},
        {"term": {"blocked": False}},
        {"term": {"safety_state": "approved"}},
        {"term": {"availability": "available"}},
    ]


def _document(source: dict[str, Any]) -> CatalogSearchDocument:
    # Vectors are excluded from fetched sources to keep responses small; the field is required.
    return CatalogSearchDocument.model_validate({**source, "embedding": source.get("embedding", ())})


class OpenSearchRetriever:
    def __init__(self, client: OpenSearchClient, index: str = READ_ALIAS) -> None:
        self._client = client
        self._index = index

    def lexical(
        self,
        text: str,
        context: ImmersiveDiscoveryContext,
        user: UserProfile | None,
        *,
        page_size: int = 20,
        source_version: str = "imd-lexical-v1",
    ) -> tuple[LexicalRetrievalResult, dict[str, str]]:
        normalized = _normalize(text)
        tokens = _tokens(normalized)
        tenant = context.request_context.tenant_id
        if not tokens:
            return self._lexical_result((), context, source_version), {}
        body = {
            "size": min(_MAX_FETCH, page_size * _OVERFETCH),
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "filter": _hard_filters(tenant),
                    "minimum_should_match": 1,
                    "should": [
                        {
                            "term": {
                                "experience_id_normalized": {"value": normalized, "boost": 100.0, "_name": "exact_id"}
                            }
                        },
                        {"term": {"creator_id": {"value": text.strip(), "boost": 90.0, "_name": "exact_creator"}}},
                        {"match_phrase": {"title": {"query": normalized, "boost": 12.0, "_name": "title_phrase"}}},
                        {"match": {"title": {"query": normalized, "boost": 5.0, "_name": "title_term"}}},
                        {"terms": {"tags": list(tokens), "boost": 3.0, "_name": "tags_term"}},
                        {"match": {"description": {"query": normalized, "boost": 1.0, "_name": "description_term"}}},
                    ],
                }
            },
        }
        hits = self._client.search(self._index, body)["hits"]["hits"]
        scored: list[tuple[CatalogSearchDocument, float, tuple[str, ...]]] = []
        for hit in hits:
            document = _document(hit["_source"])
            if not LexicalRetriever._is_eligible(document, context, user):
                continue
            scored.append((document, float(hit["_score"]), tuple(hit.get("matched_queries", ()))))
        page = tuple(scored[:page_size])
        titles = {document.experience_id: document.title for document, _, _ in page}
        return self._lexical_result(page, context, source_version, total=len(scored)), titles

    def _lexical_result(
        self,
        scored: tuple[tuple[CatalogSearchDocument, float, tuple[str, ...]], ...],
        context: ImmersiveDiscoveryContext,
        source_version: str,
        *,
        total: int = 0,
    ) -> LexicalRetrievalResult:
        scored = tuple(item for item in scored if item[2])
        maximum = max((item[1] for item in scored), default=0.0)
        candidates = tuple(
            Candidate(
                experience_id=document.experience_id,
                tenant_id=document.tenant_id,
                source="lexical",
                source_version=source_version,
                score=_bounded_score(score, maximum),
                reason_codes=tuple(dict.fromkeys(names)),
            )
            for document, score, names in scored
        )
        evidence = tuple(
            LexicalEvidence(
                experience_id=document.experience_id,
                matched_fields=tuple(dict.fromkeys(_FIELD_BY_CLAUSE.get(name, name) for name in names)),
                reason_codes=tuple(dict.fromkeys(names)),
                exact_match=bool({"exact_id", "exact_creator"} & set(names)),
                phrase_match="title_phrase" in names,
                lexical_score=round(score, 8),
            )
            for document, score, names in scored
        )
        result = CandidateSourceResult(
            source="lexical",
            source_version=source_version,
            tenant_id=context.request_context.tenant_id,
            request_id=context.request_context.request_id,
            candidates=candidates,
            degradation=Degradation.OK if candidates else Degradation.EMPTY,
        )
        return LexicalRetrievalResult(source_result=result, evidence=evidence, total_matches=total or len(candidates))

    def vector(
        self,
        query: VectorQuery,
        context: ImmersiveDiscoveryContext,
        user: UserProfile | None,
        *,
        k: int = 20,
        source_version: str = "imd-vector-v1",
    ) -> tuple[VectorRetrievalResult, dict[str, str]]:
        tenant = context.request_context.tenant_id
        fetch = min(_MAX_FETCH, k * _OVERFETCH)
        body = {
            "size": fetch,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "knn": {
                    "embedding": {
                        "vector": list(query.embedding),
                        "k": fetch,
                        # Filtering inside the ANN request keeps the neighbors eligible rather than post-trimmed.
                        "filter": {"bool": {"filter": _hard_filters(tenant)}},
                    }
                }
            },
        }
        hits = self._client.search(self._index, body)["hits"]["hits"]
        eligible: list[tuple[CatalogSearchDocument, float]] = []
        for hit in hits:
            document = _document(hit["_source"])
            if VectorRetriever._is_eligible(document, context, user):
                # Lucene cosine scores are (1 + cosine) / 2; invert to report cosine similarity.
                eligible.append((document, max(-1.0, min(1.0, 2.0 * float(hit["_score"]) - 1.0))))
        page = eligible[:k]
        candidates = tuple(
            Candidate(
                experience_id=document.experience_id,
                tenant_id=document.tenant_id,
                source="vector",
                source_version=source_version,
                score=round((cosine + 1.0) / 2.0, 8),
                reason_codes=("vector_cosine",),
            )
            for document, cosine in page
        )
        evidence = tuple(
            VectorEvidence(
                experience_id=document.experience_id,
                reason_codes=("vector_cosine",),
                cosine_similarity=round(cosine, 8),
                embedding_model_version=query.embedding_model_version,
            )
            for document, cosine in page
        )
        result = CandidateSourceResult(
            source="vector",
            source_version=source_version,
            tenant_id=context.request_context.tenant_id,
            request_id=context.request_context.request_id,
            candidates=candidates,
            degradation=Degradation.OK if candidates else Degradation.EMPTY,
        )
        titles = {document.experience_id: document.title for document, _ in page}
        return VectorRetrievalResult(source_result=result, evidence=evidence, total_matches=len(eligible)), titles
