"""Text embedders for the catalog: a deterministic local one by default, Azure OpenAI when configured."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.embedding.hashing import HASH_EMBEDDING_VERSION, HashingEmbedder

if TYPE_CHECKING:
    from app.config import DiscoverySettings

__all__ = ["HASH_EMBEDDING_VERSION", "HashingEmbedder", "create_embedder"]


def create_embedder(settings: DiscoverySettings):  # type: ignore[no-untyped-def]
    """Return the configured embedder. Hashing is the default and makes no network call."""
    if settings.embedding_provider == "azure_openai":
        from app.embedding.azure_openai import AzureOpenAIEmbedder, token_provider_for

        key_auth = settings.azure_openai_auth == "key"
        return AzureOpenAIEmbedder(
            settings.azure_openai_endpoint or "",
            settings.azure_openai_deployment or "",
            settings.azure_openai_api_key if key_auth else None,
            token_provider=None if key_auth else token_provider_for(settings.azure_openai_auth),
            dimensions=settings.embedding_dimensions,
            api_version=settings.azure_openai_api_version,
            max_texts=settings.embedding_max_texts,
            timeout=settings.request_timeout_seconds,
        )
    return HashingEmbedder(settings.embedding_dimensions)
