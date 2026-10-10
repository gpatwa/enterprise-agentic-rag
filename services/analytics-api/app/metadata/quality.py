"""Metadata actionability scoring and semantic-first asset ranking."""
from __future__ import annotations

import re

from packages.platform_contracts.metadata import (
    MetadataAsset,
    MetadataQualityReport,
    MetadataSearchResult,
    MetadataSnapshot,
)


class MetadataQualityGate:
    """Fail closed when the context lacks minimum information for planning."""

    def __init__(self, minimum_score: float = 0.75):
        self.minimum_score = minimum_score

    def evaluate(self, asset: MetadataAsset) -> MetadataQualityReport:
        missing: list[str] = []
        if not asset.description:
            missing.append("description")
        if not asset.owner_ids:
            missing.append("owner")
        if not asset.columns:
            missing.append("columns")
        if not asset.certified:
            missing.append("certification")
        score = max(0.0, 1.0 - len(missing) / 4)
        return MetadataQualityReport(
            asset_id=asset.id,
            score=score,
            actionable=score >= self.minimum_score and not missing,
            missing=missing,
            warnings=["metadata is not certified"] if not asset.certified else [],
        )


def rank_assets(query: str, snapshot: MetadataSnapshot, limit: int = 3) -> list[MetadataSearchResult]:
    """Rank assets by semantic text matches; quality gating happens separately."""
    terms = set(re.findall(r"[a-z0-9]+", query.lower()))
    results: list[MetadataSearchResult] = []
    for asset in snapshot.assets:
        text = " ".join(
            [asset.display_name, asset.physical_name, asset.description or "", *asset.tags]
            + [column.name + " " + (column.description or "") for column in asset.columns]
        ).lower()
        score = float(sum(term in text for term in terms))
        if asset.certified:
            score += 0.25
        if score > 0:
            results.append(MetadataSearchResult(asset=asset, score=score))
    return sorted(results, key=lambda result: (-result.score, result.asset.id))[:limit]
