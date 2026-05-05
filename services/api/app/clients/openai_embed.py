# services/api/app/clients/openai_embed.py
"""
OpenAI-compatible Embedding provider.
Works with: OpenAI API, Azure OpenAI, any OpenAI-compatible endpoint.

Usage:
  EMBED_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  OPENAI_EMBED_MODEL=text-embedding-3-small   # 1536 dims ($0.02/1M tokens)

Note: Switching embed providers requires re-indexing documents in Qdrant
because different models produce different vector dimensions.
  - BGE-M3 (Ray): 4096 dims
  - text-embedding-3-small: 1536 dims
  - text-embedding-3-large: 3072 dims
"""
import logging
from typing import Optional

import backoff
from openai import APIError, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class OpenAIEmbedClient:
    """Async OpenAI embedding client."""

    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        self.model = settings.OPENAI_EMBED_MODEL

    async def start(self) -> None:
        """Initialize the OpenAI async client."""
        kwargs = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL

        self.client = AsyncOpenAI(**kwargs)
        logger.info(
            "OpenAI Embed Client initialized (model=%s)",
            self.model,
        )

    async def close(self) -> None:
        """Clean up the client."""
        if self.client:
            await self.client.close()

    @backoff.on_exception(backoff.expo, APIError, max_tries=3)
    async def embed_query(self, text: str) -> list[float]:
        """Embed a single query string."""
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    @backoff.on_exception(backoff.expo, APIError, max_tries=3)
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in a single batch call."""
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        # OpenAI returns embeddings in the same order as input
        return [item.embedding for item in response.data]
