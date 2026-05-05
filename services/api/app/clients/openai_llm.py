# services/api/app/clients/openai_llm.py
"""
OpenAI-compatible LLM provider.
Works with: OpenAI API, Azure OpenAI, Together AI, Groq, any OpenAI-compatible endpoint.

Usage:
  LLM_PROVIDER=openai
  OPENAI_API_KEY=sk-...
  OPENAI_MODEL=gpt-4o-mini          # or gpt-4o, gpt-3.5-turbo, etc.
  OPENAI_BASE_URL=                   # optional, for Azure/compatible APIs
"""
import logging
from typing import AsyncGenerator, Dict, List, Optional

import backoff
from openai import APIError, AsyncOpenAI

from app.config import settings

logger = logging.getLogger(__name__)


class OpenAILLMClient:
    """Async OpenAI chat completion client."""

    def __init__(self):
        self.client: Optional[AsyncOpenAI] = None
        self.model = settings.OPENAI_MODEL

    async def start(self) -> None:
        """Initialize the OpenAI async client."""
        kwargs = {"api_key": settings.OPENAI_API_KEY}
        if settings.OPENAI_BASE_URL:
            kwargs["base_url"] = settings.OPENAI_BASE_URL

        self.client = AsyncOpenAI(**kwargs)
        logger.info(
            "OpenAI LLM Client initialized (model=%s, base_url=%s)",
            self.model,
            settings.OPENAI_BASE_URL or "https://api.openai.com",
        )

    async def close(self) -> None:
        """Clean up the client."""
        if self.client:
            await self.client.close()

    @backoff.on_exception(backoff.expo, APIError, max_tries=3)
    async def chat_completion(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        """Send chat completion via OpenAI API."""
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        kwargs = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": 1024,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = await self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    async def chat_completion_stream(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        """
        Streaming variant — yields token chunks as they are generated.
        Uses the native OpenAI streaming API.
        """
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")

        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=1024,
            stream=True,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices[0].delta else None
            if delta:
                yield delta
