"""The API ensures its vector collections at start, sized for the embedding provider (no init script, no 4096 default)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.vector_collections import collection_names, embedding_dimensions, ensure_collections


def _settings(**kw):
    base = dict(
        EMBED_PROVIDER="azure_openai", QDRANT_VECTOR_SIZE=None, QDRANT_COLLECTION="rag_collection",
        AZURE_OPENAI_EMBED_DIMENSIONS=768, GEMINI_EMBED_DIMENSIONS=768, OPENAI_EMBED_MODEL="text-embedding-3-small",
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({}, 768),
        ({"EMBED_PROVIDER": "gemini"}, 768),
        ({"EMBED_PROVIDER": "openai"}, 1536),
        ({"EMBED_PROVIDER": "openai", "OPENAI_EMBED_MODEL": "text-embedding-3-large"}, 3072),
        ({"EMBED_PROVIDER": "ray"}, 1024),
        ({"QDRANT_VECTOR_SIZE": 4096}, 4096),
    ],
)
def test_dimensions_follow_the_embedding_provider(overrides, expected) -> None:
    assert embedding_dimensions(_settings(**overrides)) == expected


def test_the_three_collections_the_app_uses_are_ensured_with_that_size() -> None:
    created = []

    class _Vectordb:
        async def create_collection(self, name, vector_size):
            created.append((name, vector_size))

    mismatched = asyncio.run(ensure_collections(_Vectordb(), _settings()))
    assert created == [(n, 768) for n in collection_names(_settings())]
    assert {n for n, _ in created} == {"rag_collection", "semantic_cache", "experience_memory"}
    assert mismatched == []


def test_a_collection_that_exists_with_another_size_is_reported() -> None:
    class _Client:
        async def get_collection(self, name):
            size = 4096 if name == "rag_collection" else 768
            return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=size))))

    class _Vectordb:
        client = _Client()

        async def create_collection(self, name, vector_size):
            pass

    assert asyncio.run(ensure_collections(_Vectordb(), _settings())) == ["rag_collection"]


def test_main_ensures_collections_right_after_connecting_the_vector_db() -> None:
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "main.py").read_text()
    assert source.index("await vectordb_client.connect()") < source.index("ensure_collections(vectordb_client, settings)")
