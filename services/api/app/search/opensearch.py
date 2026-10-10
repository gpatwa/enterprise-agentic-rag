from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import time
from collections.abc import Callable, Sequence
from typing import Any, Awaitable
from urllib.parse import urlsplit

from app.config import Settings, settings
from app.search.compatibility import MappingCompatibilityKind, classify_mapping_compatibility
from app.search.errors import OpenSearchError, normalize_opensearch_exception
from app.search.filters import compile_request_filters
from app.search.mappings import SUPPORT_SEARCH_MAPPING_VERSION, build_support_index_definition
from app.search.models import (
    BulkWriteResult,
    RankingExplanation,
    RetrievalSource,
    SearchDocument,
    SearchHealth,
    SearchIndexSpec,
    SearchMode,
    SearchRequest,
    SearchResponse,
    SearchResult,
    SearchScope,
    SearchWriteError,
)
from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION

try:
    from opensearchpy import AsyncOpenSearch
except ImportError:  # pragma: no cover - exercised by dependency-install checks
    AsyncOpenSearch = None  # type: ignore[assignment,misc]


ClientFactory = Callable[[dict[str, Any]], Any]


class _BulkItemException(Exception):
    def __init__(self, status_code: int | None, payload: Any):
        super().__init__(str(payload))
        self.status_code = status_code
        self.info = {"error": payload} if isinstance(payload, dict) else None


def _default_client_factory(options: dict[str, Any]) -> Any:
    if AsyncOpenSearch is None:
        raise RuntimeError("opensearch-py is required to construct the OpenSearch provider")
    return AsyncOpenSearch(**options)


class OpenSearchProvider:
    """Async OpenSearch lifecycle and health adapter.

    Querying and indexing methods are added in later execution milestones. Keeping
    this foundation small makes connection failures observable before rollout.
    """

    RETRY_BASE_DELAY_SECONDS = 0.1
    RETRY_MAX_DELAY_SECONDS = 2.0
    CIRCUIT_FAILURE_THRESHOLD = 3
    CIRCUIT_RESET_SECONDS = 30.0

    def __init__(
        self,
        *,
        config: Settings | None = None,
        client: Any | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.config = config or settings
        self._client = client
        self._client_factory = client_factory or _default_client_factory
        self._connected = False
        self._server_info: dict[str, Any] = {}
        self._consecutive_failures = 0
        self._circuit_open_until: float | None = None

    async def connect(self) -> None:
        if self._connected:
            return

        if self._client is None:
            self._client = self._client_factory(self._client_options())

        try:
            server_info = await self._with_retry("connect", self._client.info)
        except Exception:
            self._connected = False
            raise

        self._server_info = server_info if isinstance(server_info, dict) else {}
        self._connected = True

    async def close(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception as error:
                raise normalize_opensearch_exception(error, operation="close") from error
        self._connected = False

    async def health(self) -> SearchHealth:
        if not self._connected or self._client is None:
            return SearchHealth(
                status="not_ready",
                index_alias=self.config.OPENSEARCH_INDEX_ALIAS,
                details={"provider": "opensearch", "connected": False},
            )

        cluster = await self._with_retry("health", self._client.cluster.health)
        cluster_status = str(cluster.get("status", "unknown")) if isinstance(cluster, dict) else "unknown"
        status = "ready" if cluster_status in {"green", "yellow"} else "not_ready"
        details: dict[str, Any] = {
            "provider": "opensearch",
            "connected": True,
            "cluster_status": cluster_status,
        }
        for key in ("cluster_name", "number_of_nodes", "active_shards", "unassigned_shards"):
            if isinstance(cluster, dict) and key in cluster:
                details[key] = cluster[key]

        version = self._server_info.get("version")
        if isinstance(version, dict) and version.get("number"):
            details["version"] = version["number"]

        index_generation = None
        document_count = 0
        if getattr(self._client, "indices", None) is not None:
            metadata = await self._with_retry(
                "index_metadata",
                lambda: self._read_index_metadata(self.config.OPENSEARCH_INDEX_ALIAS),
            )
            index_generation = metadata["index_generation"]
            document_count = metadata["document_count"]
            details.update(metadata["details"])
            if metadata["alias_state"]["status"] != "active":
                status = "not_ready"

        return SearchHealth(
            status=status,
            index_alias=self.config.OPENSEARCH_INDEX_ALIAS,
            index_generation=index_generation,
            document_count=document_count,
            details=details,
        )

    async def ensure_index(self, spec: SearchIndexSpec) -> None:
        """Create or validate a physical index for a versioned generation."""
        self._require_connected()
        index_name = spec.generation
        definition = build_support_index_definition(spec.vector_dimensions)
        definition["mappings"]["_meta"] = {
            "mapping_version": SUPPORT_SEARCH_MAPPING_VERSION,
            "schema_version": spec.schema_version,
            "embedding_model_version": spec.embedding_model_version,
        }

        if not await self._index_exists(index_name):
            await self._with_retry(
                "create_index",
                lambda: self._client.indices.create(index=index_name, body=definition),
            )
            return

        existing = await self._with_retry(
            "get_mapping",
            lambda: self._client.indices.get_mapping(index=index_name),
        )
        existing_mapping = self._extract_mapping(existing, index_name)
        compatibility = classify_mapping_compatibility(existing_mapping, definition["mappings"])
        if compatibility.kind != MappingCompatibilityKind.IDENTICAL:
            reasons = ", ".join(compatibility.reasons) or "mapping content differs"
            raise ValueError(
                f"OpenSearch index {index_name!r} exists with incompatible mapping "
                f"({compatibility.kind.value} drift: {reasons}); create a new generation before retrying"
            )

    async def upsert(
        self,
        documents: Sequence[SearchDocument],
        *,
        index: str | None = None,
    ) -> BulkWriteResult:
        """Bulk-index canonical documents and preserve per-item outcomes."""
        self._require_connected()
        unique_documents = self._deduplicate_documents(documents)
        if not unique_documents:
            return BulkWriteResult(attempted=0, succeeded=0, failed=0, errors=())

        target_index = index or self.config.OPENSEARCH_INDEX_ALIAS
        body = self._bulk_body(unique_documents, target_index)
        response = await self._with_retry(
            "bulk_upsert",
            lambda: self._client.bulk(index=target_index, body=body),
        )
        items = response.get("items", []) if isinstance(response, dict) else []
        errors: list[SearchWriteError] = []
        succeeded = 0
        for position, document in enumerate(unique_documents):
            item = items[position] if position < len(items) else None
            result = self._bulk_item_result(item)
            if result is None:
                succeeded += 1
                continue
            errors.append(
                SearchWriteError(
                    document_id=document.document_id,
                    code=result[0].code,
                    message=str(result[1])[:2000],
                    retryable=result[0].retryable,
                )
            )

        succeeded = len(unique_documents) - len(errors)
        return BulkWriteResult(
            attempted=len(unique_documents),
            succeeded=succeeded,
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
        """Delete tenant-owned documents and acknowledge missing tombstones."""
        self._require_connected()
        unique_ids = self._deduplicate_ids(document_ids)
        if not unique_ids:
            return BulkWriteResult(attempted=0, succeeded=0, failed=0, errors=())

        target_index = index or self.config.OPENSEARCH_INDEX_ALIAS
        lookup = await self._with_retry(
            "delete_scope_lookup",
            lambda: self._client.mget(index=target_index, body={"ids": unique_ids}),
        )
        lookup_docs = lookup.get("docs") if isinstance(lookup, dict) else None
        if not isinstance(lookup_docs, list):
            raise ValueError("OpenSearch delete scope lookup returned an invalid response")

        errors: list[SearchWriteError] = []
        eligible_ids: list[str] = []
        lookup_by_id = {
            lookup_doc.get("_id"): lookup_doc
            for lookup_doc in lookup_docs
            if isinstance(lookup_doc, dict) and isinstance(lookup_doc.get("_id"), str)
        }
        for document_id in unique_ids:
            lookup_doc = lookup_by_id.get(document_id)
            if lookup_doc is None:
                errors.append(
                    SearchWriteError(
                        document_id=document_id,
                        code="scope_lookup",
                        message="OpenSearch did not return tenant scope metadata",
                        retryable=True,
                    )
                )
                continue
            if not isinstance(lookup_doc, dict):
                errors.append(self._scope_error(document_id))
                continue
            if lookup_doc.get("found") is False:
                eligible_ids.append(document_id)
                continue
            source = lookup_doc.get("_source")
            if not isinstance(source, dict) or source.get("tenant_id") != scope.tenant_id:
                errors.append(self._scope_error(document_id))
                continue
            eligible_ids.append(document_id)

        if eligible_ids:
            response = await self._with_retry(
                "bulk_delete",
                lambda: self._client.bulk(
                    index=target_index,
                    body=[{"delete": {"_index": target_index, "_id": document_id}} for document_id in eligible_ids],
                ),
            )
            items = response.get("items", []) if isinstance(response, dict) else []
            for position, document_id in enumerate(eligible_ids):
                item = items[position] if position < len(items) else None
                result = self._delete_item_result(item)
                if result is None:
                    continue
                errors.append(
                    SearchWriteError(
                        document_id=document_id,
                        code=result[0].code,
                        message=str(result[1])[:2000],
                        retryable=result[0].retryable,
                    )
                )

        return BulkWriteResult(
            attempted=len(unique_ids),
            succeeded=len(unique_ids) - len(errors),
            failed=len(errors),
            errors=errors,
        )

    async def search(self, request: SearchRequest) -> SearchResponse:
        """Execute lexical, vector, or deterministic hybrid retrieval."""
        self._require_connected()
        if request.mode == SearchMode.LEXICAL:
            return await self._search_lexical(request)
        if request.mode == SearchMode.VECTOR:
            return await self._search_vector(request)
        if request.mode == SearchMode.HYBRID:
            return await self._search_hybrid(request)
        raise ValueError(f"unsupported search mode: {request.mode}")

    async def _search_lexical(self, request: SearchRequest) -> SearchResponse:
        if request.cursor is not None:
            search_after = _decode_cursor(request.cursor)
        else:
            search_after = None

        body: dict[str, Any] = {
            "size": request.limit,
            "track_total_hits": True,
            "query": build_lexical_query(request),
            "_source": list(_LEXICAL_SOURCE_FIELDS),
            "sort": [{"_score": "desc"}, {"document_id": "asc"}],
            "highlight": {
                "pre_tags": ["<em>"],
                "post_tags": ["</em>"],
                "fields": {
                    "title": {"number_of_fragments": 1},
                    "text": {"fragment_size": 240, "number_of_fragments": 3},
                },
            },
        }
        if search_after is not None:
            body["search_after"] = search_after
        if request.score_threshold is not None:
            body["min_score"] = request.score_threshold

        response = await self._with_retry(
            "search",
            lambda: self._client.search(index=self.config.OPENSEARCH_INDEX_ALIAS, body=body),
        )
        hits_payload = response.get("hits", {}) if isinstance(response, dict) else {}
        hits = hits_payload.get("hits", []) if isinstance(hits_payload, dict) else []
        total = _total_hits(hits_payload)
        results: list[SearchResult] = []
        for rank, hit in enumerate(hits if isinstance(hits, list) else [], start=1):
            result = self._normalize_lexical_hit(hit, request.scope, rank)
            if result is not None:
                results.append(result)

        generation = next((result.index_generation for result in results), self.config.OPENSEARCH_INDEX_ALIAS)
        return SearchResponse(
            results=tuple(results),
            total=total,
            next_cursor=_next_cursor(hits, request.limit),
            index_alias=self.config.OPENSEARCH_INDEX_ALIAS,
            index_generation=generation,
        )

    async def _search_vector(self, request: SearchRequest) -> SearchResponse:
        if request.query_vector is None:
            raise ValueError("vector search requires query_vector")
        expected_dimensions = getattr(self.config, "OPENSEARCH_VECTOR_DIMENSIONS", None)
        if expected_dimensions and len(request.query_vector) != expected_dimensions:
            raise ValueError(
                f"query_vector dimension {len(request.query_vector)} does not match configured "
                f"dimension {expected_dimensions}"
            )
        if request.cursor is not None:
            raise NotImplementedError("vector search cursors require a provider-specific k-NN page")

        body: dict[str, Any] = {
            "size": request.limit,
            "track_total_hits": True,
            "query": {
                "knn": {
                    "embedding": {
                        "vector": list(request.query_vector),
                        "k": request.limit,
                        "filter": compile_request_filters(request),
                    }
                }
            },
            "_source": list(_LEXICAL_SOURCE_FIELDS),
        }
        if request.score_threshold is not None:
            body["min_score"] = request.score_threshold
        response = await self._with_retry(
            "vector_search",
            lambda: self._client.search(index=self.config.OPENSEARCH_INDEX_ALIAS, body=body),
        )
        return self._response_from_hits(response, request, RetrievalSource.VECTOR)

    async def _search_hybrid(self, request: SearchRequest) -> SearchResponse:
        if request.query_vector is None:
            raise ValueError("hybrid search requires query_vector")
        cursor_document_id: str | None = None
        if request.cursor is not None:
            cursor = _decode_cursor(request.cursor)
            if len(cursor) != 2 or cursor[0] != "hybrid" or not isinstance(cursor[1], str):
                raise ValueError("hybrid search cursor is invalid")
            cursor_document_id = cursor[1]
        candidate_limit = min(max(request.limit * 10, 50), 1000)
        lexical_request = request.model_copy(
            update={"mode": SearchMode.LEXICAL, "limit": candidate_limit, "cursor": None}
        )
        vector_request = request.model_copy(
            update={"mode": SearchMode.VECTOR, "limit": candidate_limit, "cursor": None}
        )
        lexical = await self._search_lexical(lexical_request)
        vector = await self._search_vector(vector_request)
        lexical_by_id = {result.document_id: result for result in lexical.results}
        vector_by_id = {result.document_id: result for result in vector.results}
        fused: list[SearchResult] = []
        rrf_k = float(getattr(self.config, "OPENSEARCH_RRF_K", 60.0))
        for document_id in sorted(set(lexical_by_id) | set(vector_by_id)):
            lexical_result = lexical_by_id.get(document_id)
            vector_result = vector_by_id.get(document_id)
            lexical_rank = lexical_result.rank if lexical_result else None
            vector_rank = vector_result.rank if vector_result else None
            rrf_score = 0.0
            if lexical_rank is not None:
                rrf_score += 1.0 / (rrf_k + lexical_rank)
            if vector_rank is not None:
                rrf_score += 1.0 / (rrf_k + vector_rank)
            base = lexical_result or vector_result
            assert base is not None
            sources = tuple(
                source
                for source in (RetrievalSource.LEXICAL, RetrievalSource.VECTOR)
                if (source == RetrievalSource.LEXICAL and lexical_result)
                or (source == RetrievalSource.VECTOR and vector_result)
            )
            fused.append(
                base.model_copy(
                    update={
                        "score": rrf_score,
                        "retrieval_source": RetrievalSource.HYBRID,
                        "lexical_score": lexical_result.lexical_score if lexical_result else None,
                        "vector_score": (
                            vector_result.vector_score
                            if vector_result and vector_result.vector_score is not None
                            else vector_result.score if vector_result else None
                        ),
                        "fusion_score": rrf_score,
                        "explanation": RankingExplanation(
                            sources=sources,
                            components={
                                "rrf": rrf_score,
                                "lexical": lexical_result.lexical_score if lexical_result else 0.0,
                                "vector": vector_result.vector_score if vector_result else 0.0,
                            },
                            notes=("Deterministic reciprocal-rank fusion",),
                        ),
                    }
                )
            )
        fused.sort(key=lambda result: (-result.fusion_score, result.document_id))
        total = len(fused)
        if cursor_document_id is not None:
            cursor_index = next(
                (index for index, result in enumerate(fused) if result.document_id == cursor_document_id),
                None,
            )
            if cursor_index is None:
                raise ValueError("hybrid search cursor does not match this result set")
            fused = fused[cursor_index + 1 :]
        selected = [result.model_copy(update={"rank": rank}) for rank, result in enumerate(fused[: request.limit], 1)]
        generation = next((result.index_generation for result in selected), self.config.OPENSEARCH_INDEX_ALIAS)
        return SearchResponse(
            results=tuple(selected),
            total=total,
            next_cursor=(
                _encode_cursor(["hybrid", selected[-1].document_id])
                if len(selected) == request.limit and selected
                else None
            ),
            index_alias=self.config.OPENSEARCH_INDEX_ALIAS,
            index_generation=generation,
        )

    def _response_from_hits(
        self,
        response: Any,
        request: SearchRequest,
        retrieval_source: RetrievalSource,
    ) -> SearchResponse:
        hits_payload = response.get("hits", {}) if isinstance(response, dict) else {}
        hits = hits_payload.get("hits", []) if isinstance(hits_payload, dict) else []
        total = _total_hits(hits_payload)
        results: list[SearchResult] = []
        for rank, hit in enumerate(hits if isinstance(hits, list) else [], start=1):
            result = self._normalize_lexical_hit(
                hit,
                request.scope,
                rank,
                retrieval_source=retrieval_source,
            )
            if result is not None:
                results.append(result)
        generation = next((result.index_generation for result in results), self.config.OPENSEARCH_INDEX_ALIAS)
        return SearchResponse(
            results=tuple(results),
            total=total,
            index_alias=self.config.OPENSEARCH_INDEX_ALIAS,
            index_generation=generation,
        )

    def _normalize_lexical_hit(
        self,
        hit: Any,
        scope: SearchScope,
        rank: int,
        *,
        retrieval_source: RetrievalSource = RetrievalSource.LEXICAL,
    ) -> SearchResult | None:
        if not isinstance(hit, dict):
            return None
        source = hit.get("_source")
        if not isinstance(source, dict) or not _source_is_visible(source, scope):
            return None
        document_id = _text_value(source.get("document_id") or hit.get("_id"))
        tenant_id = _text_value(source.get("tenant_id"))
        source_type = _text_value(source.get("source_type"))
        source_id = _text_value(source.get("source_id"))
        title = _text_value(source.get("title"))
        text = _text_value(source.get("text"))
        if not all((document_id, tenant_id, source_type, source_id, title, text)):
            return None
        raw_score = hit.get("_score", 0.0)
        score = float(raw_score) if isinstance(raw_score, (int, float)) else 0.0
        generation = _text_value(hit.get("_index")) or self.config.OPENSEARCH_INDEX_ALIAS
        content_version = _text_value(source.get("content_version")) or "unknown"
        permission_version = _text_value(source.get("permission_version")) or "unknown"
        embedding_model_version = source.get("embedding_model_version")
        if embedding_model_version is not None:
            embedding_model_version = _text_value(embedding_model_version) or None
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        highlights = _normalize_highlights(hit.get("highlight"))
        explanation = RankingExplanation(
            sources=(retrieval_source,),
            components={"bm25" if retrieval_source == RetrievalSource.LEXICAL else "vector": score},
            notes=(
                "OpenSearch BM25 lexical retrieval"
                if retrieval_source == RetrievalSource.LEXICAL
                else "OpenSearch filtered k-NN retrieval",
            ),
        )
        return SearchResult(
            document_id=document_id,
            tenant_id=tenant_id,
            source_type=source_type,
            source_id=source_id,
            title=title,
            text=text,
            metadata=metadata,
            score=max(score, 0.0),
            rank=rank,
            retrieval_source=retrieval_source,
            lexical_score=max(score, 0.0) if retrieval_source == RetrievalSource.LEXICAL else None,
            vector_score=max(score, 0.0) if retrieval_source == RetrievalSource.VECTOR else None,
            highlights=highlights,
            source_uri=_text_value(source.get("source_uri")) or None,
            index_generation=generation,
            content_version=content_version,
            permission_version=permission_version,
            embedding_model_version=embedding_model_version,
            explanation=explanation,
        )

    async def list_documents(
        self,
        *,
        index: str | None = None,
        batch_size: int = 500,
        max_documents: int = 100_000,
    ) -> list[dict[str, Any]]:
        """Return bounded source snapshots for reconciliation and reindex gates."""
        self._require_connected()
        target_index = index or self.config.OPENSEARCH_INDEX_ALIAS
        documents: list[dict[str, Any]] = []
        search_after: list[Any] | None = None
        while len(documents) < max_documents:
            body: dict[str, Any] = {
                "size": min(max(batch_size, 1), 1000),
                "query": {"match_all": {}},
                "sort": [{"document_id": "asc"}],
            }
            if search_after is not None:
                body["search_after"] = search_after
            response = await self._with_retry(
                "list_documents",
                lambda: self._client.search(index=target_index, body=body),
            )
            hits = response.get("hits", {}).get("hits", []) if isinstance(response, dict) else []
            if not isinstance(hits, list) or not hits:
                break
            for hit in hits:
                if not isinstance(hit, dict):
                    continue
                source = hit.get("_source")
                if not isinstance(source, dict):
                    continue
                copied = dict(source)
                copied.setdefault("document_id", hit.get("_id"))
                documents.append(copied)
                if len(documents) >= max_documents:
                    break
            if len(hits) < body["size"]:
                break
            last_sort = hits[-1].get("sort")
            if not isinstance(last_sort, list):
                break
            search_after = last_sort
        return documents

    @staticmethod
    def _deduplicate_ids(document_ids: Sequence[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for document_id in document_ids:
            if not isinstance(document_id, str) or not document_id.strip():
                continue
            normalized = document_id.strip()
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return unique

    @staticmethod
    def _scope_error(document_id: str) -> SearchWriteError:
        return SearchWriteError(
            document_id=document_id,
            code="tenant_scope",
            message="document is outside the requested tenant scope",
            retryable=False,
        )

    @staticmethod
    def _delete_item_result(item: Any) -> tuple[OpenSearchError, str] | None:
        if isinstance(item, dict):
            action = next(iter(item.values()), {})
            if isinstance(action, dict) and action.get("status") == 404:
                return None
        return OpenSearchProvider._bulk_item_result(item)

    @staticmethod
    def _deduplicate_documents(documents: Sequence[SearchDocument]) -> list[SearchDocument]:
        unique: list[SearchDocument] = []
        seen: set[str] = set()
        for document in documents:
            if document.document_id in seen:
                continue
            seen.add(document.document_id)
            unique.append(document)
        return unique

    def _bulk_body(self, documents: Sequence[SearchDocument], index: str) -> list[dict[str, Any]]:
        body: list[dict[str, Any]] = []
        for document in documents:
            body.append({"index": {"_index": index, "_id": document.document_id}})
            body.append(self._document_source(document))
        return body

    @staticmethod
    def _document_source(document: SearchDocument) -> dict[str, Any]:
        attributes = getattr(document, "attributes", None)
        rank_features = getattr(document, "rank_features", None)
        canonical = f"{document.title}\n{document.text}"
        content_hash = getattr(document, "content_hash", None) or hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest()
        source: dict[str, Any] = {
            "schema_version": getattr(document, "schema_version", SUPPORT_SEARCH_SCHEMA_VERSION),
            "document_id": document.document_id,
            "tenant_id": document.tenant_id,
            "acl_tokens": list(document.acl_tokens),
            "source_type": document.source_type,
            "source_id": document.source_id,
            "provider": document.provider,
            "title": document.title,
            "text": document.text,
            "source_uri": document.source_uri,
            "created_at": _serialize_datetime(getattr(document, "created_at", None)),
            "updated_at": _serialize_datetime(document.updated_at),
            "content_hash": content_hash,
            "content_version": document.content_version,
            "permission_version": document.permission_version,
            "embedding_model_version": document.embedding_model_version,
            "metadata": document.metadata,
        }
        for field in ("status", "priority", "category", "channel", "locale", "tags"):
            value = getattr(attributes, field, None)
            source[field] = list(value) if field == "tags" and value is not None else value
        for field in (
            "freshness_score",
            "quality_score",
            "resolution_confidence",
            "popularity_score",
            "engagement_score",
        ):
            source[field] = float(getattr(rank_features, field, 0.0))
        if document.vector is not None:
            source["embedding"] = list(document.vector)
        return source

    @staticmethod
    def _bulk_item_result(item: Any) -> tuple[OpenSearchError, str] | None:
        if not isinstance(item, dict):
            error = _BulkItemException(None, "missing bulk item response")
            return normalize_opensearch_exception(error, operation="bulk_upsert"), "missing bulk item response"
        action = next(iter(item.values()), {})
        if not isinstance(action, dict):
            error = _BulkItemException(None, "invalid bulk item response")
            return normalize_opensearch_exception(error, operation="bulk_upsert"), "invalid bulk item response"
        status = action.get("status")
        if isinstance(status, int) and 200 <= status < 300 and "error" not in action:
            return None
        error_payload = action.get("error") or "bulk item failed"
        status_code = status if isinstance(status, int) else None
        error = _BulkItemException(status_code, error_payload)
        normalized = normalize_opensearch_exception(error, operation="bulk_upsert")
        if isinstance(error_payload, dict):
            message = error_payload.get("reason") or error_payload.get("type") or str(error_payload)
        else:
            message = str(error_payload)
        return normalized, message

    async def activate_alias(self, alias: str, index_name: str) -> None:
        """Atomically point a stable alias at a known physical generation."""
        self._require_connected()
        alias = alias.strip()
        index_name = index_name.strip()
        if not alias or not index_name:
            raise ValueError("alias and index_name cannot be blank")
        if not await self._index_exists(index_name):
            raise ValueError(f"cannot activate unknown OpenSearch index generation: {index_name}")

        try:
            response = await self._client.indices.get_alias(name=alias)
        except Exception as error:
            if _is_not_found(error):
                response = {}
            else:
                raise normalize_opensearch_exception(error, operation="get_alias") from error

        current_indexes = self._extract_alias_indexes(response, alias)
        if current_indexes == (index_name,):
            return

        actions = [
            {"remove": {"index": current_index, "alias": alias}}
            for current_index in current_indexes
        ]
        actions.append(
            {
                "add": {
                    "index": index_name,
                    "alias": alias,
                    "is_write_index": True,
                }
            }
        )
        try:
            await self._client.indices.update_aliases(body={"actions": actions})
        except Exception as error:
            raise normalize_opensearch_exception(error, operation="activate_alias") from error

    def _require_connected(self) -> None:
        if not self._connected or self._client is None:
            raise RuntimeError("OpenSearch provider must be connected before index operations")

    async def _index_exists(self, index_name: str) -> bool:
        response = await self._with_retry(
            "index_exists",
            lambda: self._client.indices.exists(index=index_name),
        )
        if isinstance(response, bool):
            return response
        body = getattr(response, "body", None)
        return bool(response if body is None else body)

    @staticmethod
    def _extract_mapping(response: Any, index_name: str) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {}
        payload = response.get(index_name)
        if not isinstance(payload, dict):
            if len(response) != 1:
                return {}
            payload = next(iter(response.values()))
        if not isinstance(payload, dict):
            return {}
        mapping = payload.get("mappings", payload)
        return mapping if isinstance(mapping, dict) else {}

    @staticmethod
    def _extract_alias_indexes(response: Any, alias: str) -> tuple[str, ...]:
        if not isinstance(response, dict):
            return ()
        indexes = []
        for index_name, payload in response.items():
            if not isinstance(payload, dict):
                continue
            aliases = payload.get("aliases", {})
            if isinstance(aliases, dict) and alias in aliases:
                indexes.append(str(index_name))
        return tuple(sorted(indexes))

    async def _read_index_metadata(self, alias: str) -> dict[str, Any]:
        try:
            alias_response = await self._client.indices.get_alias(name=alias)
        except Exception as error:
            if _is_not_found(error):
                return {
                    "index_generation": None,
                    "document_count": 0,
                    "alias_state": {"alias": alias, "status": "missing", "indexes": [], "write_index": None},
                    "details": {
                        "alias_state": {
                            "alias": alias,
                            "status": "missing",
                            "indexes": [],
                            "write_index": None,
                        },
                        "mapping": None,
                        "model": None,
                    },
                }
            raise

        indexes = self._extract_alias_indexes(alias_response, alias)
        write_indexes = []
        for index_name in indexes:
            payload = alias_response.get(index_name, {})
            aliases = payload.get("aliases", {}) if isinstance(payload, dict) else {}
            alias_options = aliases.get(alias, {}) if isinstance(aliases, dict) else {}
            if isinstance(alias_options, dict) and alias_options.get("is_write_index") is True:
                write_indexes.append(index_name)

        write_index = write_indexes[0] if len(write_indexes) == 1 else (indexes[0] if len(indexes) == 1 else None)
        alias_status = "active" if len(indexes) == 1 else ("multiple" if indexes else "missing")
        alias_state = {
            "alias": alias,
            "status": alias_status,
            "indexes": list(indexes),
            "write_index": write_index,
        }
        if write_index is None:
            return {
                "index_generation": None,
                "document_count": 0,
                "alias_state": alias_state,
                "details": {"alias_state": alias_state, "mapping": None, "model": None},
            }

        mapping_response = await self._client.indices.get_mapping(index=write_index)
        mapping = self._extract_mapping(mapping_response, write_index)
        metadata = mapping.get("_meta", {}) if isinstance(mapping, dict) else {}
        properties = mapping.get("properties", {}) if isinstance(mapping, dict) else {}
        count_response = await self._client.count(index=write_index)
        document_count = count_response.get("count", 0) if isinstance(count_response, dict) else 0
        mapping_summary = {
            "version": metadata.get("mapping_version"),
            "schema_version": metadata.get("schema_version"),
            "field_count": len(properties) if isinstance(properties, dict) else 0,
        }
        model = metadata.get("embedding_model_version")
        return {
            "index_generation": write_index,
            "document_count": max(0, int(document_count)),
            "alias_state": alias_state,
            "details": {
                "alias_state": alias_state,
                "mapping": mapping_summary,
                "mapping_version": mapping_summary["version"],
                "model": model,
                "embedding_model_version": model,
            },
        }

    def _client_options(self) -> dict[str, Any]:
        parsed = urlsplit(self.config.get_opensearch_url())
        if not parsed.hostname:
            raise ValueError("OpenSearch URL must include a host")

        options: dict[str, Any] = {
            "hosts": [{"host": parsed.hostname, "port": parsed.port or self.config.OPENSEARCH_PORT}],
            "use_ssl": parsed.scheme.lower() == "https",
            "verify_certs": self.config.OPENSEARCH_VERIFY_CERTS,
            "timeout": self.config.OPENSEARCH_REQUEST_TIMEOUT_SECONDS,
            "max_retries": self.config.OPENSEARCH_MAX_RETRIES,
            "retry_on_timeout": self.config.OPENSEARCH_RETRY_ON_TIMEOUT,
            "pool_maxsize": self.config.OPENSEARCH_POOL_MAXSIZE,
        }

        if self.config.OPENSEARCH_CA_CERT_PATH:
            options["ca_certs"] = self.config.OPENSEARCH_CA_CERT_PATH

        auth_mode = self.config.OPENSEARCH_AUTH_MODE.strip().lower()
        if auth_mode == "basic":
            options["http_auth"] = (
                self.config.OPENSEARCH_USERNAME,
                self.config.OPENSEARCH_PASSWORD,
            )
        elif auth_mode == "api_key":
            options["headers"] = {"Authorization": f"ApiKey {self.config.OPENSEARCH_API_KEY}"}
        elif auth_mode != "none":
            raise ValueError("OPENSEARCH_AUTH_MODE must be one of: none, basic, api_key")

        return options

    async def _with_retry(self, operation: str, callback: Callable[[], Awaitable[Any]]) -> Any:
        self._ensure_circuit_closed(operation)
        max_retries = max(0, int(self.config.OPENSEARCH_MAX_RETRIES))
        for attempt in range(max_retries + 1):
            try:
                result = await callback()
            except Exception as error:
                normalized = normalize_opensearch_exception(error, operation=operation)
                if not normalized.retryable or attempt >= max_retries:
                    self._record_failure(normalized)
                    raise normalized from error
                await asyncio.sleep(self._retry_delay(attempt))
            else:
                self._record_success()
                return result

        raise AssertionError("OpenSearch retry loop exited without a result or exception")

    def _retry_delay(self, retry_number: int) -> float:
        return min(self.RETRY_MAX_DELAY_SECONDS, self.RETRY_BASE_DELAY_SECONDS * (2**retry_number))

    def _ensure_circuit_closed(self, operation: str) -> None:
        if self._circuit_open_until is None:
            return
        if time.monotonic() >= self._circuit_open_until:
            self.reset_circuit()
            return
        raise OpenSearchError(
            code="circuit_open",
            message=f"OpenSearch {operation} blocked by circuit breaker",
            retryable=True,
            operation=operation,
        )

    def _record_failure(self, error: Any) -> None:
        if not getattr(error, "retryable", False):
            return
        self._consecutive_failures += 1
        threshold = max(1, int(getattr(self, "CIRCUIT_FAILURE_THRESHOLD", 3)))
        if self._consecutive_failures >= threshold:
            self._circuit_open_until = time.monotonic() + float(self.CIRCUIT_RESET_SECONDS)

    def _record_success(self) -> None:
        self._consecutive_failures = 0
        self._circuit_open_until = None

    def reset_circuit(self) -> None:
        """Close the local circuit after an operator or readiness reset."""
        self._consecutive_failures = 0
        self._circuit_open_until = None


def _is_not_found(error: BaseException) -> bool:
    status_code = getattr(error, "status_code", None)
    if status_code == 404:
        return True
    meta = getattr(error, "meta", None)
    if getattr(meta, "status_code", None) == 404:
        return True
    return "notfound" in type(error).__name__.lower() or "not found" in str(error).lower()


def _serialize_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


_LEXICAL_SOURCE_FIELDS = (
    "document_id",
    "tenant_id",
    "acl_tokens",
    "source_type",
    "source_id",
    "provider",
    "title",
    "text",
    "metadata",
    "source_uri",
    "content_version",
    "permission_version",
    "embedding_model_version",
)


def build_lexical_query(request: SearchRequest) -> dict[str, Any]:
    """Build deterministic BM25 clauses with exact-ID and phrase boosts."""
    scoped = compile_request_filters(request)
    bool_query = scoped["bool"]
    bool_query["must"] = [
        {
            "multi_match": {
                "query": request.text,
                "fields": ["title^3", "text"],
                "type": "best_fields",
                "operator": "or",
            }
        }
    ]
    bool_query["should"] = [
        {"term": {"source_id": {"value": request.text, "boost": 8.0}}},
        {"term": {"document_id": {"value": request.text, "boost": 6.0}}},
        {"match_phrase": {"title": {"query": request.text, "boost": 4.0}}},
        {"match_phrase": {"text": {"query": request.text, "boost": 2.0}}},
    ]
    bool_query["minimum_should_match"] = 0
    return scoped


def _total_hits(hits_payload: Any) -> int:
    if not isinstance(hits_payload, dict):
        return 0
    total = hits_payload.get("total", 0)
    if isinstance(total, dict):
        total = total.get("value", 0)
    return max(int(total), 0) if isinstance(total, (int, float)) else 0


def _encode_cursor(sort_values: Any) -> str:
    if not isinstance(sort_values, list) or not sort_values or len(sort_values) > 8:
        raise ValueError("OpenSearch did not return a usable pagination sort key")
    payload = json.dumps(sort_values, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str) -> list[Any]:
    if not cursor or len(cursor) > 4096:
        raise ValueError("search cursor is invalid")
    try:
        padding = "=" * (-len(cursor) % 4)
        decoded = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        value = json.loads(decoded.decode("utf-8"))
    except (ValueError, UnicodeError, json.JSONDecodeError, binascii.Error) as error:
        raise ValueError("search cursor is invalid") from error
    if not isinstance(value, list) or not value or len(value) > 8:
        raise ValueError("search cursor is invalid")
    return value


def _next_cursor(hits: Any, limit: int) -> str | None:
    if not isinstance(hits, list) or len(hits) < limit or not hits:
        return None
    last_hit = hits[-1]
    if not isinstance(last_hit, dict):
        return None
    return _encode_cursor(last_hit.get("sort"))


def _source_is_visible(source: dict[str, Any], scope: SearchScope) -> bool:
    if source.get("tenant_id") != scope.tenant_id:
        return False
    raw_tokens = source.get("acl_tokens")
    if not isinstance(raw_tokens, (list, tuple, set, frozenset)):
        return False
    document_tokens = {token for token in raw_tokens if isinstance(token, str)}
    if f"tenant:{scope.tenant_id}" not in document_tokens:
        return False
    document_groups = {token for token in document_tokens if not token.startswith("tenant:")}
    scope_groups = {token for token in scope.acl_tokens if not token.startswith("tenant:")}
    return not document_groups or bool(document_groups.intersection(scope_groups))


def _normalize_highlights(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        return ()
    fragments: list[str] = []
    for field in ("title", "text"):
        raw_fragments = value.get(field)
        if isinstance(raw_fragments, str):
            raw_fragments = [raw_fragments]
        if not isinstance(raw_fragments, list):
            continue
        for fragment in raw_fragments:
            if isinstance(fragment, str) and fragment.strip():
                fragments.append(fragment[:2000])
                if len(fragments) >= 6:
                    return tuple(fragments)
    return tuple(fragments)


def _text_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""
