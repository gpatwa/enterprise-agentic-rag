"""Context and ontology built in-process from a certified semantic contract (pilot; no OpenSearch cluster).

For a pilot with one or a few certified contracts the whole catalogue fits in memory, so the context snapshot and the ontology are
derived from the certified contract at start-up, and retrieval is a small lexical search over that snapshot. Nothing uncertified is
ever included. An OpenSearch-backed `ContextSearchProvider` (ADS-017) can replace `SnapshotSearch` without other changes.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn
from packages.platform_contracts.ontology import OntologyEdge, OntologyNode, OntologyProvenance, OntologySnapshot
from packages.platform_contracts.semantic import SemanticRegistryDocument

_STOP = frozenset("a an the of by for and per to in on is are what how do we our me show give i can you".split())


def context_from_contract(
    document: SemanticRegistryDocument, *, now: datetime | None = None
) -> tuple[ContextSnapshot, OntologySnapshot]:
    if document.lifecycle != "certified":
        raise ValueError("context is only built from a certified contract")
    contract = document.contract
    observed = now or datetime.now(timezone.utc)
    digest = hashlib.sha256(document.model_dump_json().encode()).hexdigest()
    snapshot_id = f"{contract.id}@{contract.version}:{digest[:12]}"
    provenance = OntologyProvenance(
        source_system="semantic-registry",
        source_id=contract.id,
        source_version=contract.version,
        observed_at=observed,
        fingerprint=digest,
    )
    kinds = (
        (contract.datasets, "dataset"),
        (contract.metrics, "metric"),
        (contract.dimensions, "dimension"),
        (contract.fields, "field"),
    )
    nodes = tuple(
        OntologyNode(
            node_id=asset.id,
            tenant_id=contract.tenant_id,
            node_type=kind,
            label=getattr(asset, "display_name", None) or asset.id,
            lifecycle="certified",
            valid_from=observed - timedelta(days=1),
            provenance=(provenance.model_copy(update={"source_id": asset.id}),),
        )
        for assets, kind in kinds
        for asset in assets
    )
    edges = tuple(
        OntologyEdge(
            edge_id=f"{dataset.id}-contains-{asset.id}",
            tenant_id=contract.tenant_id,
            edge_type="contains",
            from_node_id=dataset.id,
            to_node_id=asset.id,
            valid_from=observed - timedelta(days=1),
            provenance=(provenance.model_copy(update={"source_id": f"{dataset.id}-{asset.id}"}),),
        )
        for dataset in contract.datasets
        for asset in (*contract.metrics, *contract.dimensions)
        if asset.dataset_id == dataset.id
    )
    ontology = OntologySnapshot(
        snapshot_id=snapshot_id, tenant_id=contract.tenant_id, captured_at=observed, nodes=nodes, edges=edges
    )
    datasets = tuple(
        MetadataAsset(
            id=dataset.id,
            display_name=dataset.display_name,
            physical_name=dataset.physical_name,
            provider="semantic-registry",
            description=dataset.description,
            owner_ids=dataset.owner_ids,
            certified=True,
            source_version=f"{contract.id}@{contract.version}",
            observed_at=observed,
            columns=[
                MetadataColumn(name=f.physical_name, data_type=f.data_type, classification=f.classification)
                for f in contract.fields
                if f.dataset_id == dataset.id
            ],
        )
        for dataset in contract.datasets
    )
    context = ContextSnapshot.build(
        snapshot_id=snapshot_id,
        tenant_id=contract.tenant_id,
        source_fingerprints=(digest,),
        metadata_assets=datasets,
        ontology=ontology,
        semantic_contract_ids=(f"{contract.id}@{contract.version}",),
        created_at=observed,
    )
    return context, ontology


class FixedSnapshots:
    """Serves one context snapshot and its ontology by exact ID and tenant."""

    def __init__(self, context: ContextSnapshot, ontology: OntologySnapshot) -> None:
        self.context, self.ontology = context, ontology

    def get(self, snapshot_id: str, tenant_id: str) -> ContextSnapshot:
        if (snapshot_id, tenant_id) != (self.context.snapshot_id, self.context.tenant_id):
            raise LookupError("context snapshot scope mismatch")
        return self.context

    def current_snapshot(self) -> ContextSnapshot:
        return self.context


class FixedOntology:
    def __init__(self, ontology: OntologySnapshot) -> None:
        self.ontology = ontology

    def get(self, snapshot_id: str, tenant_id: str) -> OntologySnapshot:
        if (snapshot_id, tenant_id) != (self.ontology.snapshot_id, self.ontology.tenant_id):
            raise LookupError("ontology snapshot scope mismatch")
        return self.ontology


class SnapshotSearch:
    """Lexical search over the certified datasets of one snapshot; returns at least the best dataset so the pack is never empty."""

    def __init__(self, context: ContextSnapshot) -> None:
        self.context = context

    def search(self, query: str, *, tenant_id: str, snapshot_id: str, certified_only: bool = True, limit: int = 10):
        if (tenant_id, snapshot_id) != (self.context.tenant_id, self.context.snapshot_id):
            return ()
        terms = {t for t in re.findall(r"[a-z0-9]+", query.lower()) if t not in _STOP}
        scored = []
        for asset in self.context.metadata_assets:
            if certified_only and not asset.certified:
                continue
            text = " ".join(
                [asset.display_name, asset.physical_name, asset.description or "", *(c.name for c in asset.columns)]
            )
            score = len(terms & set(re.findall(r"[a-z0-9]+", text.lower())))
            scored.append((score, asset, text))
        scored.sort(key=lambda item: (-item[0], item[1].id))
        return tuple(
            ContextPackItem(
                asset_id=asset.id,
                score=float(score),
                text=text[:2_000],
                citation=f"context:{snapshot_id}:{asset.id}",
                certified=asset.certified,
            )
            for score, asset, text in scored[:limit]
        )


class CertifiedContracts:
    """`get_certified` for exactly the contracts loaded at start-up."""

    def __init__(self, documents: list[SemanticRegistryDocument]) -> None:
        self._documents = {(d.contract.id, d.contract.version): d for d in documents if d.lifecycle == "certified"}

    def get_certified(self, contract_id: str, version: str) -> SemanticRegistryDocument:
        try:
            return self._documents[(contract_id, version)]
        except KeyError as exc:
            raise LookupError("exact certified contract not found") from exc
