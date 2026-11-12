# pipelines/ingestion/embedding/compute.py
import logging
import os
from typing import Any, Dict, Mapping

import httpx

logger = logging.getLogger(__name__)


class BatchEmbedder:
    """
    Callable Class for Ray Data.
    Maintains a session for efficiency.
    """
    def __init__(self):
        # We hardcode internal DNS for Ray Service
        self.endpoint = "http://ray-serve-embed:8000/embed"
        self.client = httpx.Client(timeout=30.0)

    def __call__(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receives a batch of text chunks.
        Returns the batch with 'vector' field added.
        """
        texts = batch["text"]

        try:
            response = self.client.post(
                self.endpoint,
                json={"text": texts, "task_type": "document"}
            )
            response.raise_for_status()
            embeddings = response.json()["embeddings"]

            # Add embeddings to the batch dictionary
            batch["vector"] = embeddings
            return batch

        except Exception as e:
            # In Ray, raising exception triggers retry logic automatically
            raise e


class GeminiBatchEmbedder:
    """
    Text-only Ray Data embedder that calls Gemini and returns ``GEMINI_EMBED_DIMENSIONS`` (default 768) vectors.

    This is the ingestion counterpart of the API's ``GeminiEmbedClient``: both ask for the same model and the same
    Matryoshka size, so a chunk embedded here is searchable with a query embedded there, and both fit the 768-dim
    OpenSearch index. Unlike ``MultimodalBatchEmbedder`` it never swallows a failure: an error or a wrong-sized
    vector raises, so Ray retries the batch and nothing is written with a vector that does not belong in the index.
    """

    # The Gemini embedContent API accepts at most 100 texts per request.
    MAX_BATCH = 100

    def __init__(self):
        self.gemini_client = None
        self.model = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2-preview")
        self.dimensions = int(os.getenv("GEMINI_EMBED_DIMENSIONS", "768"))

    def _ensure_client(self):
        if self.gemini_client is None:
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise RuntimeError("GOOGLE_API_KEY required for the Gemini ingestion embedder (INGEST_EMBED_PROVIDER=gemini)")
            from google import genai

            self.gemini_client = genai.Client(api_key=api_key)

    def __call__(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        from google.genai import types

        self._ensure_client()
        texts = list(batch["text"])
        vectors = []
        for start in range(0, len(texts), self.MAX_BATCH):
            result = self.gemini_client.models.embed_content(
                model=self.model,
                contents=texts[start : start + self.MAX_BATCH],
                config=types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=self.dimensions,
                ),
            )
            vectors.extend(list(e.values) for e in result.embeddings)

        if len(vectors) != len(texts):
            raise ValueError(f"Gemini returned {len(vectors)} vectors for {len(texts)} chunks")
        for vector in vectors:
            if len(vector) != self.dimensions:
                raise ValueError(f"Gemini returned a {len(vector)}-dimension vector but {self.dimensions} was requested")
        batch["vector"] = vectors
        return batch


def select_text_embedder(env: Mapping[str, str]):
    """The text embedder class for ``INGEST_EMBED_PROVIDER``: ``ray`` (default, the BGE-M3 Serve endpoint) or ``gemini``."""
    provider = (env.get("INGEST_EMBED_PROVIDER") or "ray").strip().lower()
    if provider == "ray":
        return BatchEmbedder
    if provider == "gemini":
        return GeminiBatchEmbedder
    raise ValueError(f"INGEST_EMBED_PROVIDER must be 'ray' or 'gemini', got {provider!r}")


class MultimodalBatchEmbedder:
    """
    Callable Class for Ray Data with multimodal support.
    Routes ALL content through Gemini for unified embedding space.
    Text and images must share the same vector space for cross-modal retrieval.
    """
    def __init__(self):
        self.gemini_client = None
        self.model = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-2-preview")
        self.dimensions = int(os.getenv("GEMINI_EMBED_DIMENSIONS", "768"))

    def _ensure_client(self):
        if self.gemini_client is None:
            from google import genai
            api_key = os.getenv("GOOGLE_API_KEY")
            if not api_key:
                raise RuntimeError("GOOGLE_API_KEY required for MultimodalBatchEmbedder")
            self.gemini_client = genai.Client(api_key=api_key)

    def __call__(self, batch: Dict[str, Any]) -> Dict[str, Any]:
        """
        Receives a batch with content_type, text, image_bytes, mime_type fields.
        Embeds everything via Gemini for a unified vector space.
        Returns the batch with 'vector' field added.
        """
        from google.genai import types

        self._ensure_client()

        content_types = batch.get("content_type", ["text"] * len(batch["text"]))
        vectors = []

        for i, ct in enumerate(content_types):
            try:
                if ct == "image":
                    image_bytes = batch["image_bytes"][i]
                    mime_type = batch["mime_type"][i]
                    part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
                    result = self.gemini_client.models.embed_content(
                        model=self.model,
                        contents=part,
                        config=types.EmbedContentConfig(
                            task_type="RETRIEVAL_DOCUMENT",
                            output_dimensionality=self.dimensions,
                        ),
                    )
                else:
                    text = batch["text"][i]
                    result = self.gemini_client.models.embed_content(
                        model=self.model,
                        contents=text,
                        config=types.EmbedContentConfig(
                            task_type="RETRIEVAL_DOCUMENT",
                            output_dimensionality=self.dimensions,
                        ),
                    )
                vectors.append(list(result.embeddings[0].values))
            except Exception as e:
                logger.error(f"Embedding failed for item {i} (type={ct}): {e}")
                vectors.append(None)

        batch["vector"] = vectors
        return batch
