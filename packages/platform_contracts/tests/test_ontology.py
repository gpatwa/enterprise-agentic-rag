from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.platform_contracts.ontology import OntologyEdge, OntologyNode, OntologyProvenance, OntologySnapshot


def provenance(source_id: str = "orders") -> OntologyProvenance:
    return OntologyProvenance(
        source_system="dbt", source_id=source_id, source_version="run-1",
        observed_at=datetime.now(timezone.utc), fingerprint="a" * 64,
    )


def node(node_id: str, tenant_id: str = "tenant-a") -> OntologyNode:
    return OntologyNode(
        node_id=node_id, tenant_id=tenant_id, node_type="dataset", label=node_id,
        valid_from=datetime.now(timezone.utc), provenance=(provenance(node_id),),
    )


def test_ontology_snapshot_validates_cross_references_tenant_and_provenance():
    snapshot = OntologySnapshot(
        snapshot_id="snapshot-1", tenant_id="tenant-a", nodes=(node("orders"), node("customers")),
        edges=(OntologyEdge(
            edge_id="orders-customers", tenant_id="tenant-a", edge_type="depends_on",
            from_node_id="orders", to_node_id="customers", valid_from=datetime.now(timezone.utc),
            provenance=(provenance(),),
        ),),
    )
    assert snapshot.nodes[0].provenance[0].source_system == "dbt"
    assert OntologySnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda values: values["edges"].__setitem__(0, values["edges"][0].model_copy(update={"to_node_id": "missing"})), "unknown node"),
        (lambda values: values["nodes"].__setitem__(1, values["nodes"][1].model_copy(update={"tenant_id": "tenant-b"})), "tenant"),
    ],
)
def test_ontology_snapshot_rejects_invalid_graph(mutate, message):
    values = {
        "snapshot_id": "snapshot-1", "tenant_id": "tenant-a", "nodes": [node("orders"), node("customers")],
        "edges": [OntologyEdge(
            edge_id="orders-customers", tenant_id="tenant-a", edge_type="depends_on",
            from_node_id="orders", to_node_id="customers", valid_from=datetime.now(timezone.utc),
            provenance=(provenance(),),
        )],
    }
    mutate(values)
    with pytest.raises(ValidationError, match=message):
        OntologySnapshot(**values)


def test_ontology_temporal_range_is_monotonic():
    start = datetime.now(timezone.utc)
    with pytest.raises(ValidationError, match="valid_to"):
        OntologyNode(
            node_id="orders", tenant_id="tenant-a", node_type="dataset", label="orders",
            valid_from=start, valid_to=start, provenance=(provenance(),),
        )
