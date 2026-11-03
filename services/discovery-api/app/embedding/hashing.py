"""Feature-hashing text embedder: deterministic, local, and model-free.

Each word and adjacent word pair is hashed into a fixed number of signed buckets and the result is
L2-normalized, so cosine similarity measures weighted word overlap. It is not a semantic model: it
will not relate "cozy" to "relaxing". It exists so the vector retrieval path runs end to end on
synthetic data without a model call, a cost, or a network dependency.
"""

from __future__ import annotations

import hashlib
import math
import re

HASH_EMBEDDING_VERSION = "imd-hash-embedding-v1"
_TOKEN = re.compile(r"\w+", re.UNICODE)
_BIGRAM_WEIGHT = 0.5


class HashingEmbedder:
    """Map text to a unit vector of ``dimensions`` floats; identical text gives an identical vector."""

    model_version = HASH_EMBEDDING_VERSION

    def __init__(self, dimensions: int = 384) -> None:
        if not 8 <= dimensions <= 4096:
            raise ValueError("dimensions must be between 8 and 4096")
        self.dimensions = dimensions

    def embed(self, text: str) -> tuple[float, ...]:
        tokens = _TOKEN.findall(text.lower())
        if not tokens:
            raise ValueError("text has no embeddable tokens")
        vector = [0.0] * self.dimensions
        for token in tokens:
            self._add(vector, token, 1.0)
        for left, right in zip(tokens, tokens[1:]):
            self._add(vector, f"{left} {right}", _BIGRAM_WEIGHT)
        norm = math.sqrt(sum(value * value for value in vector))
        return tuple(value / norm for value in vector)

    def _add(self, vector: list[float], feature: str, weight: float) -> None:
        digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
        bucket = int.from_bytes(digest[:6], "big") % self.dimensions
        vector[bucket] += weight if digest[6] & 1 else -weight

    def embed_document(self, title: str, description: str, tags: tuple[str, ...]) -> tuple[float, ...]:
        """Embed catalog fields with the title counted twice, mirroring the lexical title weight."""
        return self.embed(" ".join((title, title, description, *tags)))
