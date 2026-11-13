# services/api/app/clients/azure_openai.py
"""
Azure OpenAI LLM and embedding clients — keyless.

They authenticate with Entra ID tokens from ``DefaultAzureCredential``: the pod's workload identity in AKS, the
developer's own ``az login`` on a laptop. No API key exists to store, rotate or expire; the account has key
authentication turned off (infra/terraform/azure/openai.tf).

Usage:
  LLM_PROVIDER=azure_openai
  EMBED_PROVIDER=azure_openai
  AZURE_OPENAI_ENDPOINT=https://<account>.openai.azure.com/
  AZURE_OPENAI_LLM_DEPLOYMENT=gpt-6-luna
  AZURE_OPENAI_EMBED_DEPLOYMENT=text-embedding-3-small
  AZURE_OPENAI_EMBED_DIMENSIONS=768

Embeddings are requested at ``AZURE_OPENAI_EMBED_DIMENSIONS`` (768, Matryoshka) so they fit the 768-dim indexes, and a
vector of any other size raises instead of being written.
"""
import logging
from typing import AsyncGenerator, Dict, List, Optional

import backoff
from openai import APIError, AsyncAzureOpenAI, BadRequestError

from app.config import settings

logger = logging.getLogger(__name__)

COGNITIVE_SCOPE = "https://cognitiveservices.azure.com/.default"


class _AzureOpenAIBase:
    """Shared construction of the token-authenticated client."""

    def __init__(self) -> None:
        self.client: Optional[AsyncAzureOpenAI] = None
        self._credential = None

    async def _open(self) -> AsyncAzureOpenAI:
        endpoint = settings.AZURE_OPENAI_ENDPOINT
        if not endpoint:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT is required for the azure_openai provider")
        from azure.identity.aio import DefaultAzureCredential, get_bearer_token_provider

        self._credential = DefaultAzureCredential()
        return AsyncAzureOpenAI(
            azure_endpoint=endpoint,
            api_version=settings.AZURE_OPENAI_API_VERSION,
            azure_ad_token_provider=get_bearer_token_provider(self._credential, COGNITIVE_SCOPE),
        )

    async def close(self) -> None:
        if self.client:
            await self.client.close()
            self.client = None
        if self._credential:
            await self._credential.close()
            self._credential = None


class AzureOpenAILLMClient(_AzureOpenAIBase):
    """
    Async Azure OpenAI chat completion client.

    Newer chat models differ from the 4o family: they take ``max_completion_tokens`` (not ``max_tokens``) and some only
    accept the default ``temperature``. The client always sends ``max_completion_tokens`` and, when the service rejects a
    custom temperature, retries once without it and remembers that for this model.
    """

    def __init__(self, model: Optional[str] = None) -> None:
        super().__init__()
        self.model = model or settings.AZURE_OPENAI_LLM_DEPLOYMENT  # the deployment name
        self._omit_temperature = False

    async def start(self) -> None:
        self.client = await self._open()
        logger.info("Azure OpenAI LLM client initialised (deployment=%s, keyless)", self.model)

    async def _create(self, messages: List[Dict], temperature: float, stream: bool = False, **extra):
        kwargs = {"model": self.model, "messages": messages, "max_completion_tokens": 1024, **extra}
        if stream:
            kwargs["stream"] = True
        if not self._omit_temperature:
            kwargs["temperature"] = temperature
        try:
            return await self.client.chat.completions.create(**kwargs)
        except BadRequestError as exc:
            if "temperature" not in str(exc).lower() or "temperature" not in kwargs:
                raise
            logger.info("Deployment %s only accepts the default temperature; retrying without it", self.model)
            self._omit_temperature = True
            kwargs.pop("temperature")
            return await self.client.chat.completions.create(**kwargs)

    @backoff.on_exception(backoff.expo, APIError, max_tries=3, giveup=lambda e: isinstance(e, BadRequestError))
    async def chat_completion(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
        json_mode: bool = False,
    ) -> str:
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")
        extra = {"response_format": {"type": "json_object"}} if json_mode else {}
        response = await self._create(messages, temperature, **extra)
        return response.choices[0].message.content

    async def chat_completion_stream(
        self,
        messages: List[Dict],
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")
        stream = await self._create(messages, temperature, stream=True)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AzureOpenAIEmbedClient(_AzureOpenAIBase):
    """Async Azure OpenAI embedding client returning ``AZURE_OPENAI_EMBED_DIMENSIONS`` (default 768) vectors."""

    def __init__(self, model: Optional[str] = None) -> None:
        super().__init__()
        self.model = model or settings.AZURE_OPENAI_EMBED_DEPLOYMENT  # the deployment name
        self.dimensions = settings.AZURE_OPENAI_EMBED_DIMENSIONS

    async def start(self) -> None:
        self.client = await self._open()
        logger.info(
            "Azure OpenAI Embed client initialised (deployment=%s, dims=%d, keyless)", self.model, self.dimensions
        )

    def _check(self, vectors: list[list[float]]) -> list[list[float]]:
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"embedding has {len(vector)} dimensions, expected {self.dimensions}")
        return vectors

    @backoff.on_exception(backoff.expo, APIError, max_tries=3)
    async def embed_query(self, text: str) -> list[float]:
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")
        response = await self.client.embeddings.create(model=self.model, input=text, dimensions=self.dimensions)
        return self._check([response.data[0].embedding])[0]

    @backoff.on_exception(backoff.expo, APIError, max_tries=3)
    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not self.client:
            raise RuntimeError("Client not initialized. Call start() first.")
        response = await self.client.embeddings.create(model=self.model, input=texts, dimensions=self.dimensions)
        return self._check([item.embedding for item in response.data])
