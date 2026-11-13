# services/api/app/vector_collections.py
"""
Make sure the vector collections the app and the ingestion pipeline use exist, sized for the embedding provider.

Until now the only way to create them was ``scripts/init_qdrant.py`` (a manual step, hard-coded to 4096 dimensions).
The API now ensures them at start. ``create_collection`` is idempotent, so a restart changes nothing; a collection that
exists with another size is reported loudly because every upsert into it would fail.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Dimensions a provider yields when the setting does not say otherwise.
RAY_BGE_M3_DIMENSIONS = 1024
OPENAI_SMALL_DIMENSIONS = 1536
OPENAI_LARGE_DIMENSIONS = 3072


def embedding_dimensions(settings) -> int:
    """Vector size for ``settings.EMBED_PROVIDER`` (``QDRANT_VECTOR_SIZE`` overrides)."""
    override = getattr(settings, "QDRANT_VECTOR_SIZE", None)
    if override:
        return int(override)
    provider = (settings.EMBED_PROVIDER or "").lower().strip()
    if provider == "azure_openai":
        return int(settings.AZURE_OPENAI_EMBED_DIMENSIONS)
    if provider == "gemini":
        return int(settings.GEMINI_EMBED_DIMENSIONS)
    if provider == "openai":
        return OPENAI_LARGE_DIMENSIONS if "large" in settings.OPENAI_EMBED_MODEL else OPENAI_SMALL_DIMENSIONS
    return RAY_BGE_M3_DIMENSIONS


def collection_names(settings) -> list[str]:
    from app.cache.semantic import CACHE_COLLECTION
    from app.learning.store import EXPERIENCE_COLLECTION

    return [settings.QDRANT_COLLECTION, CACHE_COLLECTION, EXPERIENCE_COLLECTION]


async def _existing_size(vectordb, name: str) -> Optional[int]:
    """Vector size of an existing collection, when the backend can tell (Qdrant can)."""
    client = getattr(vectordb, "client", None)
    if client is None or not hasattr(client, "get_collection"):
        return None
    try:
        info = await client.get_collection(name)
        vectors = info.config.params.vectors
        return int(vectors.size) if hasattr(vectors, "size") else None
    except Exception:
        return None


async def ensure_collections(vectordb, settings) -> list[str]:
    """Create any missing collection; return the names whose existing size does not match."""
    size = embedding_dimensions(settings)
    mismatched: list[str] = []
    for name in collection_names(settings):
        await vectordb.create_collection(name, vector_size=size)
        existing = await _existing_size(vectordb, name)
        if existing is not None and existing != size:
            mismatched.append(name)
            logger.error(
                "Collection '%s' has %d dimensions but %s embeddings are %d; writes and searches will fail until "
                "it is recreated", name, existing, settings.EMBED_PROVIDER, size,
            )
    logger.info("Vector collections ensured (%s dims): %s", size, ", ".join(collection_names(settings)))
    return mismatched
