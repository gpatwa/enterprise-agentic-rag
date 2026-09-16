from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.context import OpenSearchContextIndex, build_context_index_mapping, evaluate_context_quality
from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot, build_context_pack
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn, MetadataFreshness
from packages.platform_contracts.ontology import OntologyEdge, OntologyNode, OntologyProvenance, OntologySnapshot


def snapshot(*, stale: bool = False, source_version: str | None = "dbt-run-1") -> ContextSnapshot:
    asset = MetadataAsset(
        id="orders", display_name="Orders", physical_name="orders", provider="dbt",
        description="Certified orders", certified=True, source_version=source_version,
        columns=[MetadataColumn(name="order_id", data_type="integer")],
        freshness=MetadataFreshness(stale=stale),
        observed_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )
    return ContextSnapshot.build(
        snapshot_id="snapshot-1", tenant_id="tenant-a", source_fingerprints=("a" * 64,),
        metadata_assets=(asset,), semantic_contract_ids=("commerce@v1",),
        created_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
    )


def test_context_snapshot_is_content_addressed_and_rejects_forged_fingerprint():
    current = snapshot()
    assert ContextSnapshot.model_validate_json(current.model_dump_json()) == current
    assert snapshot().content_fingerprint == current.content_fingerprint
    assert snapshot(source_version="dbt-run-2").content_fingerprint != current.content_fingerprint
    forged = current.model_dump()
    forged["content_fingerprint"] = "b" * 64
    with pytest.raises(ValidationError, match="content_fingerprint"):
        ContextSnapshot(**forged)


def test_context_pack_is_tenant_scoped_certified_and_bounded():
    current = snapshot()
    results = (
        ContextPackItem(asset_id="orders", score=0.9, text="orders " * 20, citation="snapshot-1:orders", certified=True),
        ContextPackItem(asset_id="uncertified", score=1.0, text="should omit", citation="candidate", certified=False),
    )
    pack = build_context_pack(current, results, query="orders", token_budget=50)
    assert pack.estimated_tokens <= 50
    assert [item.asset_id for item in pack.items] == ["orders"]
    assert pack.omitted_asset_ids == ("uncertified",)


def test_context_pack_adds_bounded_certified_graph_closure():
    provenance = OntologyProvenance(
        source_system="catalog", source_id="orders", source_version="v1",
        observed_at=datetime(2026, 9, 16, tzinfo=timezone.utc), fingerprint="a" * 64,
    )
    ontology = OntologySnapshot(
        snapshot_id="ontology-1", tenant_id="tenant-a",
        captured_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        nodes=(
            OntologyNode(
                node_id="orders", tenant_id="tenant-a", node_type="dataset", label="Orders",
                lifecycle="certified", valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                provenance=(provenance,),
            ),
            OntologyNode(
                node_id="customers", tenant_id="tenant-a", node_type="dataset", label="Customers",
                lifecycle="certified", valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
                provenance=(provenance.model_copy(update={"source_id": "customers"}),),
            ),
        ),
        edges=(OntologyEdge(
            edge_id="orders-customers", tenant_id="tenant-a", edge_type="joins",
            from_node_id="orders", to_node_id="customers",
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc), provenance=(provenance,),
        ),),
    )
    base = snapshot()
    current = ContextSnapshot.build(
        snapshot_id=base.snapshot_id, tenant_id=base.tenant_id,
        source_fingerprints=base.source_fingerprints, metadata_assets=base.metadata_assets,
        ontology=ontology, semantic_contract_ids=base.semantic_contract_ids, created_at=base.created_at,
    )
    pack = build_context_pack(
        current, (ContextPackItem(asset_id="orders", score=1, text="orders", citation="orders", certified=True),),
        query="orders", token_budget=50,
    )
    assert [relation.edge_id for relation in pack.graph_closure] == ["orders-customers"]
    assert pack.estimated_tokens <= pack.token_budget


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Client:
    def __init__(self):
        self.calls = []

    def post(self, url, *, json):
        self.calls.append((url, json))
        if url.endswith("/_search"):
            return Response({"hits": {"hits": [{"_score": 2, "_source": {"tenant_id": "tenant-a", "asset_id": "orders", "snapshot_id": "snapshot-1", "text": "orders", "certified": True}}]}})
        return Response({"errors": False})


def test_opensearch_index_owns_tenant_and_certification_filters():
    client = Client()
    index = OpenSearchContextIndex("http://opensearch:9200", "context-v1", client)
    assert index.index_snapshot(snapshot()) == 1
    results = index.search("orders", tenant_id="tenant-a")
    body = client.calls[-1][1]
    assert results[0].asset_id == "orders"
    assert {tuple(item["term"].items())[0] for item in body["query"]["bool"]["filter"]} == {
        ("tenant_id", "tenant-a"), ("certified", True)
    }
    assert build_context_index_mapping()["mappings"]["properties"]["tenant_id"]["type"] == "keyword"


def test_quality_gate_blocks_stale_or_unprovenanced_context():
    report = evaluate_context_quality(snapshot(stale=True), minimum_provenance=1.0)
    assert report.actionable is False
    assert report.blocking_reasons == ("stale metadata",)
    report = evaluate_context_quality(snapshot(source_version=None))
    assert report.actionable is False
    assert report.blocking_reasons == ("incomplete provenance",)
