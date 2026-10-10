from __future__ import annotations

from collections.abc import Mapping, Sequence


def precision_at_k(recommended: Sequence[str], accepted: set[str], *, k: int = 5) -> float:
    if k < 1:
        raise ValueError("k must be at least 1")
    return len(set(recommended[:k]) & accepted) / min(k, max(len(recommended), 1))


def recall_at_k(recommended: Sequence[str], accepted: set[str], *, k: int = 5) -> float:
    if k < 1:
        raise ValueError("k must be at least 1")
    return len(set(recommended[:k]) & accepted) / max(len(accepted), 1)


def coverage(recommended_by_query: Mapping[str, Sequence[str]], catalog: set[str]) -> float:
    return len({item for values in recommended_by_query.values() for item in values} & catalog) / max(len(catalog), 1)


def novelty(recommended: Sequence[str], popular: set[str]) -> float:
    return len(set(recommended) - popular) / max(len(set(recommended)), 1)
