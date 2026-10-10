from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Iterable

from app.search.events import InteractionKind, SearchInteractionEvent
from app.search.features import RankingFeatures, decay_recency


def materialize_features(
    events: Iterable[SearchInteractionEvent],
    *,
    now: datetime | None = None,
) -> dict[tuple[str, str], RankingFeatures]:
    """Build deterministic tenant/document features from consented, unexpired events."""
    current = now or datetime.now(timezone.utc)
    counts: Counter[tuple[str, str]] = Counter()
    accepts: Counter[tuple[str, str]] = Counter()
    latest: dict[tuple[str, str], datetime] = {}
    for event in events:
        if not event.consent_granted or event.expires_at <= current or not event.document_id:
            continue
        key = (event.tenant_id, event.document_id)
        counts[key] += 1
        if event.kind in {InteractionKind.ACCEPT, InteractionKind.RESOLVE}:
            accepts[key] += 1
        latest[key] = max(latest.get(key, event.occurred_at), event.occurred_at)
    return {
        key: RankingFeatures(
            recency=decay_recency(timestamp, now=current),
            popularity=min(counts[key] / 10.0, 1.0),
            expertise=min(accepts[key] / 5.0, 1.0),
            content_quality=min((counts[key] + accepts[key]) / 20.0, 1.0),
            provenance=("interaction-events.v1",),
        )
        for key, timestamp in latest.items()
    }
