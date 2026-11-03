"""Deterministic local text embedding for the demo catalog."""

from app.embedding.hashing import HASH_EMBEDDING_VERSION, HashingEmbedder

__all__ = ["HASH_EMBEDDING_VERSION", "HashingEmbedder"]
