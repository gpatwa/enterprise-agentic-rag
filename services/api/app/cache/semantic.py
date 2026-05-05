# services/api/app/cache/semantic.py
import logging
import uuid
from typing import List, Optional, Tuple

from app.clients.ray_embed import embed_client
from app.config import settings

logger = logging.getLogger(__name__)

DEFAULT_TENANT_ID = "default"
CACHE_COLLECTION = "semantic_cache"

# Late-initialised — set by main.py lifespan via set_vectordb_client()
_vectordb_client = None


def set_vectordb_client(client):
    """Called once during app startup to inject the abstracted VectorDB client."""
    global _vectordb_client
    _vectordb_client = client


class SemanticCache:
    """
    Implements Semantic Caching using Vector Search.
    Instead of exact string matching, we match by meaning.
    All cache entries are scoped by tenant_id for isolation.

    Uses the provider-agnostic VectorDBClient so caching works with
    Qdrant, Azure AI Search, or any other VectorDB backend.
    """

    async def get_cached_response(
        self,
        query: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        threshold: float | None = None,
    ) -> Optional[str]:
        """
        Check if a similar query exists in the cache for this tenant.
        """
        try:
            if threshold is None:
                threshold = settings.SEMANTIC_CACHE_THRESHOLD

            # 1. Embed the incoming query (Fast CPU/GPU call)
            vector = await embed_client.embed_query(query)

            # 2. Search in the cache collection, filtered by tenant
            cache_filters = {} if settings.SINGLE_TENANT_MODE else {"tenant_id": tenant_id}
            results = await _vectordb_client.search(
                collection=CACHE_COLLECTION,
                vector=vector,
                limit=1,
                filters=cache_filters,
                score_threshold=threshold,
            )

            if results:
                hit = results[0]
                logger.info(
                    f"Semantic Cache Hit! Score: {hit['score']} (tenant={tenant_id})"
                )
                return hit["payload"]["answer"]

        except Exception as e:
            logger.warning(f"Semantic cache lookup failed: {e}")

        return None

    async def get_cached_response_with_embedding(
        self,
        query: str,
        tenant_id: str = DEFAULT_TENANT_ID,
        threshold: float | None = None,
    ) -> Tuple[Optional[str], List[float]]:
        """
        Check semantic cache and return both the cached answer (if any) AND
        the query embedding vector.  This avoids a redundant embed call in the
        retriever when the cache misses.
        """
        if threshold is None:
            threshold = settings.SEMANTIC_CACHE_THRESHOLD

        try:
            vector = await embed_client.embed_query(query)

            cache_filters = {} if settings.SINGLE_TENANT_MODE else {"tenant_id": tenant_id}
            results = await _vectordb_client.search(
                collection=CACHE_COLLECTION,
                vector=vector,
                limit=1,
                filters=cache_filters,
                score_threshold=threshold,
            )

            if results:
                hit = results[0]
                logger.info(
                    f"Semantic Cache Hit! Score: {hit['score']} (tenant={tenant_id})"
                )
                return hit["payload"]["answer"], vector

        except Exception as e:
            logger.warning(f"Semantic cache lookup failed: {e}")
            return None, []

        return None, vector

    async def set_cached_response(
        self,
        query: str,
        answer: str,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        """
        Save a Q&A pair to the cache, tagged with tenant_id.
        """
        try:
            # 1. Embed query
            vector = await embed_client.embed_query(query)

            # 2. Save to Vector DB with tenant_id in payload
            payload = {"query": query, "answer": answer}
            if not settings.SINGLE_TENANT_MODE:
                payload["tenant_id"] = tenant_id
            await _vectordb_client.upsert(
                collection=CACHE_COLLECTION,
                points=[
                    {
                        "id": str(uuid.uuid4()),
                        "vector": vector,
                        "payload": payload,
                    }
                ],
            )
        except Exception as e:
            logger.warning(f"Failed to write to semantic cache: {e}")


semantic_cache = SemanticCache()
