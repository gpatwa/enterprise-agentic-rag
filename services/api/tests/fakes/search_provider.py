from __future__ import annotations

import re
from collections.abc import Sequence

from app.search.base import EnterpriseSearchProvider
from app.search.models import (
    BulkWriteResult,
    FilterOperator,
    RankingExplanation,
    RetrievalSource,
    SearchDocument,
    SearchHealth,
    SearchIndexSpec,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchScope,
    SearchWriteError,
)


class InMemorySearchProvider:
    """Deterministic fake used to exercise the provider contract and corpus."""

    def __init__(self) -> None:
        self.connected = False
        self._documents: dict[tuple[str, str], SearchDocument] = {}
        self._indexes: dict[str, SearchIndexSpec] = {}
        self._aliases: dict[str, str] = {}

    async def connect(self) -> None:
        self.connected = True

    async def close(self) -> None:
        self.connected = False

    async def health(self) -> SearchHealth:
        active_index = self._aliases.get("support-search")
        active_spec = self._indexes.get(active_index) if active_index else None
        return SearchHealth(
            status="ready" if self.connected and active_spec else "not_ready",
            index_alias="support-search",
            index_generation=active_spec.generation if active_spec else None,
            document_count=len(self._documents),
            details={"provider": "in_memory", "connected": self.connected},
        )

    async def ensure_index(self, spec: SearchIndexSpec) -> None:
        existing = self._indexes.get(spec.generation)
        if existing is not None and existing != spec:
            raise ValueError(f"index generation already exists with different specification: {spec.generation}")
        self._indexes[spec.generation] = spec

    async def activate_alias(self, alias: str, index_name: str) -> None:
        if index_name not in self._indexes:
            raise ValueError(f"cannot activate unknown index generation: {index_name}")
        self._aliases[alias] = index_name

    async def upsert(
        self,
        documents: Sequence[SearchDocument],
        *,
        index: str | None = None,
    ) -> BulkWriteResult:
        del index
        errors: list[SearchWriteError] = []
        for document in documents:
            key = (document.tenant_id, document.document_id)
            self._documents[key] = document
        return BulkWriteResult(
            attempted=len(documents),
            succeeded=len(documents),
            failed=len(errors),
            errors=errors,
        )

    async def delete(
        self,
        document_ids: Sequence[str],
        *,
        scope: SearchScope,
        index: str | None = None,
    ) -> BulkWriteResult:
        del index
        attempted = len(document_ids)
        errors: list[SearchWriteError] = []
        for document_id in document_ids:
            key = (scope.tenant_id, document_id)
            self._documents.pop(key, None)
        return BulkWriteResult(
            attempted=attempted,
            succeeded=attempted,
            failed=len(errors),
            errors=errors,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        candidates = [
            document
            for document in self._documents.values()
            if _is_visible(document, request.scope) and _matches_filters(document, request)
        ]
        scored = [
            (document, _lexical_score(request.text, document))
            for document in candidates
        ]
        scored = [(document, score) for document, score in scored if score > 0.0]
        scored.sort(key=lambda item: (-item[1], item[0].document_id))
        selected = scored[: request.limit]
        generation = self._active_generation()
        results = tuple(
            SearchResult(
                document_id=document.document_id,
                tenant_id=document.tenant_id,
                source_type=document.source_type,
                source_id=document.source_id,
                title=document.title,
                text=document.text,
                metadata=document.metadata,
                score=round(score, 6),
                rank=rank,
                retrieval_source=RetrievalSource.LEXICAL,
                lexical_score=round(score, 6),
                fusion_score=round(score, 6),
                source_uri=document.source_uri,
                index_generation=generation,
                content_version=document.content_version,
                permission_version=document.permission_version,
                embedding_model_version=document.embedding_model_version,
                explanation=RankingExplanation(
                    sources=(RetrievalSource.LEXICAL,),
                    components={"lexical": round(score, 6)},
                    notes=("in-memory test provider",),
                ),
            )
            for rank, (document, score) in enumerate(selected, start=1)
        )
        return SearchResponse(
            results=results,
            total=len(scored),
            index_alias="support-search",
            index_generation=generation,
        )

    def _active_generation(self) -> str:
        active_index = self._aliases.get("support-search")
        if active_index and active_index in self._indexes:
            return self._indexes[active_index].generation
        return "memory-v0"


def _is_visible(document: SearchDocument, scope: SearchScope) -> bool:
    if document.tenant_id != scope.tenant_id:
        return False
    document_groups = {token for token in document.acl_tokens if not token.startswith("tenant:")}
    scope_groups = {token for token in scope.acl_tokens if not token.startswith("tenant:")}
    return not document_groups or bool(document_groups & scope_groups)


def _matches_filters(document: SearchDocument, request: SearchRequest) -> bool:
    for search_filter in request.filters:
        actual = _field_value(document, search_filter.field)
        expected = search_filter.value
        operator = search_filter.operator
        if operator == FilterOperator.EQ and actual != expected:
            return False
        if operator == FilterOperator.NE and actual == expected:
            return False
        if operator == FilterOperator.IN and actual not in expected:
            return False
        if operator == FilterOperator.NOT_IN and actual in expected:
            return False
        if operator == FilterOperator.PREFIX and not isinstance(actual, str):
            return False
        if operator == FilterOperator.PREFIX and not actual.startswith(str(expected)):
            return False
        if operator == FilterOperator.GT and not actual > expected:
            return False
        if operator == FilterOperator.GTE and not actual >= expected:
            return False
        if operator == FilterOperator.LT and not actual < expected:
            return False
        if operator == FilterOperator.LTE and not actual <= expected:
            return False
    return True


def _field_value(document: SearchDocument, field: str):
    if field == "tenant_id":
        return document.tenant_id
    if field == "source_type":
        return document.source_type
    if field == "source_id":
        return document.source_id
    if field == "provider":
        return document.provider
    if field == "title":
        return document.title
    return document.metadata.get(field)


def _lexical_score(query: str, document: SearchDocument) -> float:
    query_terms = _tokens(query)
    if not query_terms:
        return 0.0
    title_terms = _tokens(document.title)
    body_terms = _tokens(document.text)
    title_hits = sum(term in title_terms for term in query_terms)
    body_hits = sum(term in body_terms for term in query_terms)
    score = (title_hits * 2.0 + body_hits) / (len(query_terms) * 3.0)
    return min(score, 1.0)


def _tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_-]{1,}", value.lower())


assert isinstance(InMemorySearchProvider(), EnterpriseSearchProvider)
