# services/api/app/clients/ray_llm.py
import json
import logging
from typing import AsyncGenerator, Dict, List, Optional

import backoff
import httpx

from app.config import settings

logger = logging.getLogger(__name__)

class RayLLMClient:
    """
    Async Client with proper Connection Pooling.
    """
    def __init__(self):
        self.endpoint = settings.RAY_LLM_ENDPOINT
        # Client is initialized in startup_event
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self):
        """Called during App Startup"""
        # Limits: prevent opening too many connections to Ray
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=50)
        self.client = httpx.AsyncClient(
            timeout=120.0,
            limits=limits
        )
        logger.info("Ray LLM Client initialized.")

    async def close(self):
        """Called during App Shutdown"""
        if self.client:
            await self.client.aclose()

    @backoff.on_exception(backoff.expo, httpx.HTTPError, max_tries=3)
    async def chat_completion(self, messages: List[Dict], temperature: float = 0.7, json_mode: bool = False) -> str:
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        payload = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 1024,
            "stream": False
        }

        response = await self.client.post(self.endpoint, json=payload)
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    async def chat_completion_stream(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming variant — yields token chunks as they are generated.
        Compatible with vLLM / OpenAI-style SSE endpoints.
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        payload = {
            "model": settings.LLM_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 1024,
            "stream": True,
        }
        async with self.client.stream("POST", self.endpoint, json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: ") and line.strip() != "data: [DONE]":
                    try:
                        chunk = json.loads(line[6:])
                        delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield delta
                    except (json.JSONDecodeError, IndexError, KeyError):
                        continue

# Global Instance — created via factory based on LLM_PROVIDER env var.
# Consumers import `llm_client` from this module; the factory decides
# whether it's a RayLLMClient, OpenAILLMClient, etc.
# Late import is intentional: the factory references this module's class.
from app.clients.factory import create_llm_client as _create_llm  # noqa: E402

llm_client = _create_llm(settings.LLM_PROVIDER)
