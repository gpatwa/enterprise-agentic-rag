# services/api/app/clients/ray_embed.py
import asyncio
import logging
from typing import Optional

import backoff
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

class RayEmbedClient:
    """
    Client for the Embedding Service.
    Supports both Ray Serve (prod) and Ollama (local dev) APIs.
    Ollama endpoint: POST /api/embeddings {"model": "...", "prompt": "..."}
    """
    def __init__(self):
        self.endpoint = settings.RAY_EMBED_ENDPOINT
        self.model = settings.EMBED_MODEL
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self):
        """Called during App Startup — initializes the connection pool."""
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        self.client = httpx.AsyncClient(timeout=60.0, limits=limits)
        logger.info("Embed Client initialized.")

    async def close(self):
        """Called during App Shutdown."""
        if self.client:
            await self.client.aclose()

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)
    async def embed_query(self, text: str) -> list[float]:
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")
        response = await self.client.post(
            self.endpoint,
            json={"model": self.model, "prompt": text}
        )
        response.raise_for_status()
        return response.json()["embedding"]

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)
    async def embed_documents(self, texts: list[str], batch_size: int = 10) -> list[list[float]]:
        """
        Embed multiple texts concurrently in batches.
        Sends up to `batch_size` concurrent requests to the embedding service,
        dramatically reducing wall-clock time for bulk embeddings.
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        all_embeddings: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            tasks = [
                self.client.post(
                    self.endpoint,
                    json={"model": self.model, "prompt": text},
                )
                for text in batch
            ]
            responses = await asyncio.gather(*tasks)
            for response in responses:
                response.raise_for_status()
                all_embeddings.append(response.json()["embedding"])
        return all_embeddings

# Global Instance — created via factory based on EMBED_PROVIDER env var.
# Consumers import `embed_client` from this module; the factory decides
# whether it's a RayEmbedClient, OpenAIEmbedClient, etc.
# Late import is intentional: the factory references this module's class.
from app.clients.factory import create_embed_client as _create_embed  # noqa: E402

embed_client = _create_embed(settings.EMBED_PROVIDER)
