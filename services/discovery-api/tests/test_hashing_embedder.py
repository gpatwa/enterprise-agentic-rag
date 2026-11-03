import math

import pytest

from app.embedding import HASH_EMBEDDING_VERSION, HashingEmbedder


def _cos(left, right):
    return sum(a * b for a, b in zip(left, right))


def test_embedding_is_deterministic_unit_length_and_sized() -> None:
    embedder = HashingEmbedder(384)
    first = embedder.embed("Cloud workshop above a living city")

    assert first == embedder.embed("Cloud workshop above a living city")
    assert len(first) == 384
    assert math.isclose(math.sqrt(sum(v * v for v in first)), 1.0, rel_tol=1e-9)
    assert embedder.model_version == HASH_EMBEDDING_VERSION


def test_overlapping_text_scores_higher_than_unrelated_text() -> None:
    embedder = HashingEmbedder()
    query = embedder.embed("cloud workshop")

    assert _cos(query, embedder.embed("Cloud Workshop 003 build a floating workshop")) > 0.3
    assert _cos(query, embedder.embed("racing solar skiffs through a coral maze")) < 0.2


def test_text_without_tokens_is_rejected() -> None:
    with pytest.raises(ValueError):
        HashingEmbedder().embed("  !!! ")


def test_dimensions_are_bounded() -> None:
    with pytest.raises(ValueError):
        HashingEmbedder(4)
