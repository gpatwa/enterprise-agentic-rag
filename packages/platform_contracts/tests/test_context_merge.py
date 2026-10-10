from datetime import datetime, timezone

from packages.platform_contracts.context_merge import MetadataTombstone, merge_metadata_snapshots
from packages.platform_contracts.metadata import MetadataAsset, MetadataSnapshot


def asset(provider: str, description: str, certified: bool = False) -> MetadataAsset:
    return MetadataAsset(
        id="warehouse.orders", display_name="Orders", physical_name="orders", provider=provider,
        description=description, certified=certified, tags=[provider],
    )


def test_merge_uses_explicit_precedence_and_reports_conflicts():
    result = merge_metadata_snapshots((
        MetadataSnapshot(provider="postgres", assets=[asset("postgres", "physical")]),
        MetadataSnapshot(provider="dbt", assets=[asset("dbt", "certified", True)]),
        MetadataSnapshot(provider="openmetadata", assets=[asset("openmetadata", "catalog")]),
    ))

    selected = result.snapshot.assets[0]
    assert selected.provider == "dbt"
    assert selected.description == "certified"
    assert selected.tags == ["dbt", "openmetadata", "postgres"]
    assert {item.field for item in result.conflicts} == {"description", "certified"}


def test_tombstone_from_higher_precedence_source_removes_asset():
    result = merge_metadata_snapshots(
        (MetadataSnapshot(provider="postgres", assets=[asset("postgres", "physical")]),),
        tombstones=(MetadataTombstone(
            asset_id="warehouse.orders", source="dbt", source_version="run-1",
            observed_at=datetime.now(timezone.utc), reason="model removed",
        ),),
    )

    assert result.snapshot.assets == []
    assert result.applied_tombstones[0].reason == "model removed"


def test_lower_precedence_tombstone_does_not_remove_higher_precedence_asset():
    result = merge_metadata_snapshots(
        (MetadataSnapshot(provider="dbt", assets=[asset("dbt", "certified", True)]),),
        tombstones=(MetadataTombstone(
            asset_id="warehouse.orders", source="postgres", source_version="scan-1",
            observed_at=datetime.now(timezone.utc), reason="physical table missing",
        ),),
    )

    assert len(result.snapshot.assets) == 1
    assert result.applied_tombstones == ()
