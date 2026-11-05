"""Azure OpenAI text embeddings behind the same interface as the hashing embedder.

This is a billable model call. Guards: a hard cap on texts sent per process (``max_texts``), a small cache
so repeated text is never sent twice, batching, and bounded retries on throttling or server errors only.
Error messages carry the HTTP status and nothing else: never the input text, the key, or the response body.
Construction makes no network call.
"""

from __future__ import annotations

import math
import time
from collections import OrderedDict
from typing import Callable, Sequence

import httpx

BATCH_SIZE = 16
RETRYABLE = {429, 500, 502, 503, 504}


class EmbeddingError(RuntimeError):
    """The embedding service failed or answered with something unusable."""


class EmbeddingBudgetExceeded(EmbeddingError):
    """The per-process cap on embedded texts was reached; nothing further is sent."""


class AzureOpenAIEmbedder:
    is_billable = True

    def __init__(
        self,
        endpoint: str,
        deployment: str,
        api_key: str,
        *,
        dimensions: int = 384,
        api_version: str = "2024-10-21",
        model_label: str = "text-embedding-3-small",
        timeout: float = 10.0,
        max_retries: int = 3,
        max_texts: int | None = 1000,
        cache_size: int = 256,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not endpoint.startswith("https://"):
            raise ValueError("the Azure OpenAI endpoint must be https")
        if not deployment.strip() or not api_key.strip():
            raise ValueError("deployment and api_key are required")
        if not 8 <= dimensions <= 4096:
            raise ValueError("dimensions must be between 8 and 4096")
        self.dimensions = dimensions
        self.model_version = f"azure-openai-{model_label}-d{dimensions}"
        self._url = f"{endpoint.rstrip('/')}/openai/deployments/{deployment}/embeddings"
        self._api_version = api_version
        self._key = api_key
        self._max_retries = max_retries
        self._max_texts = max_texts
        self._sent = 0
        self._cache: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._cache_size = cache_size
        self._sleep = sleep
        self._http = httpx.Client(timeout=timeout, transport=transport)

    def __repr__(self) -> str:  # never show the key
        return f"AzureOpenAIEmbedder(model_version={self.model_version!r})"

    @property
    def texts_sent(self) -> int:
        return self._sent

    def close(self) -> None:
        self._http.close()

    def embed(self, text: str) -> tuple[float, ...]:
        if not text.strip():
            raise ValueError("text has no embeddable tokens")
        return self.embed_many([text])[0]

    def embed_document(self, title: str, description: str, tags: tuple[str, ...]) -> tuple[float, ...]:
        return self.embed(" ".join((title, title, description, *tags)))

    def prefetch(self, texts: Sequence[str]) -> None:
        """Embed many texts in batches so later single calls are served from the cache."""
        self.embed_many([t for t in texts if t.strip()])

    def embed_many(self, texts: Sequence[str]) -> list[tuple[float, ...]]:
        missing = list(dict.fromkeys(t for t in texts if t not in self._cache))
        for start in range(0, len(missing), BATCH_SIZE):
            batch = missing[start : start + BATCH_SIZE]
            for text, vector in zip(batch, self._request(batch)):
                self._cache[text] = vector
                if len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        out = []
        for text in texts:
            if text not in self._cache:  # evicted by a very large call: fetch again, still bounded by max_texts
                self._cache[text] = self._request([text])[0]
            self._cache.move_to_end(text)
            out.append(self._cache[text])
        return out

    def _request(self, batch: list[str]) -> list[tuple[float, ...]]:
        if self._max_texts is not None and self._sent + len(batch) > self._max_texts:
            raise EmbeddingBudgetExceeded(f"embedding cap of {self._max_texts} texts reached")
        self._sent += len(batch)
        status = None
        for attempt in range(self._max_retries + 1):
            try:
                response = self._http.post(
                    self._url,
                    params={"api-version": self._api_version},
                    headers={"api-key": self._key},
                    json={"input": batch, "dimensions": self.dimensions},
                )
            except httpx.TransportError as exc:
                status = type(exc).__name__
            else:
                status = response.status_code
                if status == 200:
                    return self._parse(response, len(batch))
                if status not in RETRYABLE:
                    raise EmbeddingError(f"embedding request rejected (HTTP {status})")
            if attempt < self._max_retries:
                self._sleep(min(0.5 * 2**attempt, 8.0))
        raise EmbeddingError(f"embedding service unavailable after {self._max_retries + 1} attempts ({status})")

    def _parse(self, response: httpx.Response, expected: int) -> list[tuple[float, ...]]:
        try:
            items = sorted(response.json()["data"], key=lambda item: item["index"])
        except (ValueError, KeyError, TypeError) as exc:
            raise EmbeddingError("embedding response was not in the expected shape") from exc
        if len(items) != expected:
            raise EmbeddingError("embedding response did not match the request")
        vectors = []
        for item in items:
            vector = item.get("embedding")
            if not isinstance(vector, list) or len(vector) != self.dimensions:
                raise EmbeddingError("embedding had an unexpected size")
            if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in vector):
                raise EmbeddingError("embedding contained a non-finite value")
            norm = math.sqrt(sum(v * v for v in vector))
            if norm == 0.0:
                raise EmbeddingError("embedding was all zeros")
            vectors.append(tuple(float(v) / norm for v in vector))
        return vectors
