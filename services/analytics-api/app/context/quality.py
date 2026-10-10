"""Deterministic context freshness, provenance, and certification quality gate."""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.platform_contracts.context_merge import MergedMetadataSnapshot
from packages.platform_contracts.context_snapshot import ContextPack, ContextSnapshot


class ContextQualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    asset_count: int = Field(ge=0)
    certified_asset_count: int = Field(ge=0)
    provenance_coverage: float = Field(ge=0, le=1)
    stale_asset_count: int = Field(ge=0)
    conflict_count: int = Field(ge=0)
    pack_token_utilization: float = Field(ge=0, le=1)
    actionable: bool
    blocking_reasons: tuple[str, ...] = ()


def evaluate_context_quality(
    snapshot: ContextSnapshot,
    *,
    merged: MergedMetadataSnapshot | None = None,
    pack: ContextPack | None = None,
    minimum_provenance: float = 1.0,
) -> ContextQualityReport:
    assets = snapshot.metadata_assets
    coverage = sum(bool(asset.source_version) for asset in assets) / len(assets) if assets else 0.0
    stale_count = sum(bool(asset.freshness and asset.freshness.stale) for asset in assets)
    conflicts = len(merged.conflicts) if merged else 0
    utilization = (pack.estimated_tokens / pack.token_budget) if pack else 0.0
    reasons: list[str] = []
    if coverage < minimum_provenance:
        reasons.append("incomplete provenance")
    if stale_count:
        reasons.append("stale metadata")
    if conflicts:
        reasons.append("unresolved source conflicts")
    return ContextQualityReport(
        snapshot_id=snapshot.snapshot_id, asset_count=len(assets),
        certified_asset_count=sum(asset.certified for asset in assets), provenance_coverage=coverage,
        stale_asset_count=stale_count, conflict_count=conflicts, pack_token_utilization=utilization,
        actionable=not reasons, blocking_reasons=tuple(reasons),
    )
