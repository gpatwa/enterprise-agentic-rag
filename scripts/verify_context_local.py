"""Run the local live OpenSearch and semantic-context verification drill."""
from __future__ import annotations

import time
from datetime import datetime, timezone

import httpx

from app.context import OpenSearchContextIndex, evaluate_context_quality
from packages.platform_contracts.context_snapshot import ContextSnapshot
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn, MetadataFreshness

BASE_URL = "http://localhost:9200"
INDEX = "context-m1-verify"
NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)


def make_snapshot(tenant_id: str, snapshot_id: str) -> ContextSnapshot:
    assets = (
        MetadataAsset(
            id="orders", display_name="Orders", physical_name="orders", provider="dbt",
            description=f"Certified orders for {tenant_id}", certified=True,
            source_version=f"{tenant_id}-dbt-1", observed_at=NOW,
            columns=[MetadataColumn(name="order_id", data_type="integer")],
            freshness=MetadataFreshness(stale=False),
        ),
        MetadataAsset(
            id="draft-orders", display_name="Draft Orders", physical_name="draft_orders", provider="dbt",
            description=f"Uncertified draft for {tenant_id}", certified=False,
            source_version=f"{tenant_id}-dbt-1", observed_at=NOW,
            freshness=MetadataFreshness(stale=False),
        ),
    )
    return ContextSnapshot.build(
        snapshot_id=snapshot_id, tenant_id=tenant_id,
        source_fingerprints=(f"{tenant_id}-source-1".ljust(64, "0"),),
        metadata_assets=assets, semantic_contract_ids=("commerce@v1",), created_at=NOW,
    )


def wait_for_opensearch(client: httpx.Client) -> None:
    for _ in range(60):
        try:
            response = client.get(f"{BASE_URL}/_cluster/health")
            if response.is_success:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise RuntimeError("local OpenSearch did not become healthy within 60 seconds")


def main() -> None:
    with httpx.Client(timeout=20.0) as client:
        wait_for_opensearch(client)
        client.delete(f"{BASE_URL}/{INDEX}")
        adapter = OpenSearchContextIndex(BASE_URL, INDEX, client)
        adapter.create_index()
        tenant_a = make_snapshot("tenant-a", "snapshot-a")
        tenant_b = make_snapshot("tenant-b", "snapshot-b")
        assert adapter.index_snapshot(tenant_a) == 2
        assert adapter.index_snapshot(tenant_b) == 2
        client.post(f"{BASE_URL}/{INDEX}/_refresh").raise_for_status()

        a_certified = adapter.search("orders", tenant_id="tenant-a")
        b_certified = adapter.search("orders", tenant_id="tenant-b")
        assert [item.asset_id for item in a_certified] == ["orders"], a_certified
        assert [item.asset_id for item in b_certified] == ["orders"], b_certified

        a_all = adapter.search("orders", tenant_id="tenant-a", certified_only=False)
        b_all = adapter.search("orders", tenant_id="tenant-b", certified_only=False)
        assert {item.asset_id for item in a_all} == {"orders", "draft-orders"}, a_all
        assert {item.asset_id for item in b_all} == {"orders", "draft-orders"}, b_all

        good_report = evaluate_context_quality(tenant_a, minimum_provenance=1.0)
        assert good_report.actionable is True
        assert good_report.provenance_coverage == 1.0
        round_trip = ContextSnapshot.model_validate_json(tenant_a.model_dump_json())
        assert round_trip.content_fingerprint == tenant_a.content_fingerprint

        stale_asset = tenant_a.metadata_assets[0].model_copy(
            update={"freshness": MetadataFreshness(stale=True)}
        )
        stale_snapshot = ContextSnapshot.build(
            snapshot_id="snapshot-stale", tenant_id="tenant-a",
            source_fingerprints=tenant_a.source_fingerprints,
            metadata_assets=(stale_asset, tenant_a.metadata_assets[1]),
            semantic_contract_ids=tenant_a.semantic_contract_ids, created_at=NOW,
        )
        blocked_report = evaluate_context_quality(stale_snapshot, minimum_provenance=1.0)
        assert blocked_report.actionable is False
        assert "stale metadata" in blocked_report.blocking_reasons

    print("OpenSearch cluster: healthy")
    print(f"Index: {INDEX}")
    print("Indexed documents: 4")
    print("Tenant/certified isolation: PASS")
    print("Tenant/unfiltered retrieval: PASS")
    print("Snapshot round-trip and fingerprint: PASS")
    print("Quality gate good context: PASS")
    print("Quality gate stale context: BLOCKED as expected")


if __name__ == "__main__":
    main()
