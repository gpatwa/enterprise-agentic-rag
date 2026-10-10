"""Deterministic source precedence, conflict, and tombstone contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from packages.platform_contracts.metadata import MetadataAsset, MetadataSnapshot

DEFAULT_SOURCE_PRECEDENCE: tuple[str, ...] = ("compass", "dbt", "openmetadata", "postgres", "duckdb")


class MetadataTombstone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str = Field(min_length=1, max_length=512)
    source: str = Field(min_length=1, max_length=100)
    source_version: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    reason: str = Field(min_length=1, max_length=1_000)


class MetadataConflict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str
    field: str
    providers: tuple[str, ...]
    selected_provider: str
    resolution: Literal["precedence", "tombstone", "identical"]


class MergedMetadataSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot: MetadataSnapshot
    precedence: tuple[str, ...]
    conflicts: tuple[MetadataConflict, ...] = ()
    applied_tombstones: tuple[MetadataTombstone, ...] = ()


def merge_metadata_snapshots(
    snapshots: tuple[MetadataSnapshot, ...],
    *,
    tombstones: tuple[MetadataTombstone, ...] = (),
    precedence: tuple[str, ...] = DEFAULT_SOURCE_PRECEDENCE,
) -> MergedMetadataSnapshot:
    """Merge source evidence by explicit provider order, never iteration order."""
    rank = {provider: index for index, provider in enumerate(precedence)}
    ordered = sorted(snapshots, key=lambda item: (rank.get(item.provider, len(rank)), item.provider))
    by_asset: dict[str, list[MetadataAsset]] = {}
    for snapshot in ordered:
        for asset in snapshot.assets:
            by_asset.setdefault(asset.id, []).append(asset)
    tombstone_by_asset = {item.asset_id: item for item in tombstones}
    merged: list[MetadataAsset] = []
    conflicts: list[MetadataConflict] = []
    applied: list[MetadataTombstone] = []
    for asset_id, candidates in sorted(by_asset.items()):
        candidates.sort(key=lambda item: (rank.get(item.provider, len(rank)), item.provider))
        tombstone = tombstone_by_asset.get(asset_id)
        if tombstone and rank.get(tombstone.source, len(rank)) <= rank.get(candidates[0].provider, len(rank)):
            applied.append(tombstone)
            continue
        selected = candidates[0]
        for field in ("display_name", "physical_name", "description", "certified", "classification"):
            values = {str(getattr(item, field)) for item in candidates}
            if len(values) > 1:
                conflicts.append(MetadataConflict(
                    asset_id=asset_id, field=field,
                    providers=tuple(item.provider for item in candidates),
                    selected_provider=selected.provider, resolution="precedence",
                ))
        merged.append(_combine(selected, candidates))
    captured = max((item.captured_at for item in snapshots), default=datetime.now(timezone.utc))
    return MergedMetadataSnapshot(
        snapshot=MetadataSnapshot(provider="merged", captured_at=captured, assets=merged),
        precedence=precedence, conflicts=tuple(conflicts), applied_tombstones=tuple(applied),
    )


def _combine(selected: MetadataAsset, candidates: list[MetadataAsset]) -> MetadataAsset:
    return selected.model_copy(update={
        "owner_ids": sorted({value for item in candidates for value in item.owner_ids}),
        "tags": sorted({value for item in candidates for value in item.tags}),
        "lineage_asset_ids": sorted({value for item in candidates for value in item.lineage_asset_ids}),
        "upstream_asset_ids": sorted({value for item in candidates for value in item.upstream_asset_ids}),
        "downstream_asset_ids": sorted({value for item in candidates for value in item.downstream_asset_ids}),
        "glossary_terms": [term for item in candidates for term in item.glossary_terms],
        "tests": [test for item in candidates for test in item.tests],
        "exposures": [exposure for item in candidates for exposure in item.exposures],
        "metrics": [metric for item in candidates for metric in item.metrics],
    })
