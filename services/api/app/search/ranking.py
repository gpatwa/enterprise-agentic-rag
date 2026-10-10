from __future__ import annotations

from collections.abc import Mapping, Sequence

from app.search.features import RankingFeatures, default_features
from app.search.models import SearchResult


def rerank_authorized(
    results: Sequence[SearchResult],
    features_by_document: Mapping[str, RankingFeatures],
    *,
    weights: Mapping[str, float] | None = None,
) -> tuple[SearchResult, ...]:
    """Rerank an already ACL-filtered result set; this function never fetches data."""
    active_weights = {"recency": 0.1, "popularity": 0.1, "expertise": 0.1, "role_match": 0.05, "content_quality": 0.05}
    active_weights.update(weights or {})
    ranked = []
    for result in results:
        feature = features_by_document.get(result.document_id, default_features())
        adjustment = sum(getattr(feature, name) * value for name, value in active_weights.items())
        ranked.append((result.score + adjustment, result))
    ranked.sort(key=lambda item: (-item[0], item[1].document_id))
    return tuple(
        result.model_copy(update={"score": max(score, 0.0), "rank": rank})
        for rank, (score, result) in enumerate(ranked, 1)
    )
