from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class RankingFeatures:
    schema_version: str = "search-features.v1"
    recency: float = 0.0
    popularity: float = 0.0
    expertise: float = 0.0
    role_match: float = 0.0
    content_quality: float = 0.0
    provenance: tuple[str, ...] = ()


def default_features() -> RankingFeatures:
    return RankingFeatures()


def decay_recency(updated_at: datetime | None, *, now: datetime | None = None, half_life_days: float = 30.0) -> float:
    if updated_at is None or half_life_days <= 0:
        return 0.0
    current = now or datetime.now(timezone.utc)
    timestamp = updated_at if updated_at.tzinfo else updated_at.replace(tzinfo=timezone.utc)
    age_days = max((current - timestamp).total_seconds() / 86400, 0.0)
    return 2 ** (-age_days / half_life_days)
