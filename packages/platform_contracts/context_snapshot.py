"""Immutable, provenance-addressable context snapshots and bounded packs."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.metadata import MetadataAsset
from packages.platform_contracts.ontology import OntologySnapshot

CONTEXT_SNAPSHOT_VERSION = "v1"


class ContextSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_version: Literal["v1"] = CONTEXT_SNAPSHOT_VERSION
    snapshot_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    created_at: datetime
    source_fingerprints: tuple[str, ...] = Field(min_length=1)
    metadata_assets: tuple[MetadataAsset, ...] = ()
    ontology: OntologySnapshot | None = None
    semantic_contract_ids: tuple[str, ...] = ()
    content_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_scope(self) -> "ContextSnapshot":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("context snapshot created_at must be timezone-aware")
        if any(asset.id != asset.id.strip() for asset in self.metadata_assets):
            raise ValueError("context snapshot asset IDs must be canonical")
        if self.ontology and self.ontology.tenant_id != self.tenant_id:
            raise ValueError("context snapshot ontology tenant does not match snapshot tenant")
        expected = hashlib.sha256(_canonical(self._fingerprint_values()).encode()).hexdigest()
        if expected != self.content_fingerprint:
            raise ValueError("context snapshot content_fingerprint does not match content")
        return self

    def _fingerprint_values(self) -> dict[str, Any]:
        return {
            "snapshot_version": self.snapshot_version, "snapshot_id": self.snapshot_id,
            "tenant_id": self.tenant_id, "source_fingerprints": self.source_fingerprints,
            "metadata_assets": [asset.model_dump(mode="json") for asset in self.metadata_assets],
            "ontology": self.ontology.model_dump(mode="json") if self.ontology else None,
            "semantic_contract_ids": self.semantic_contract_ids,
        }

    @classmethod
    def build(
        cls,
        *,
        snapshot_id: str,
        tenant_id: str,
        source_fingerprints: tuple[str, ...],
        metadata_assets: tuple[MetadataAsset, ...] = (),
        ontology: OntologySnapshot | None = None,
        semantic_contract_ids: tuple[str, ...] = (),
        created_at: datetime | None = None,
    ) -> "ContextSnapshot":
        values: dict[str, Any] = {
            "snapshot_version": CONTEXT_SNAPSHOT_VERSION,
            "snapshot_id": snapshot_id,
            "tenant_id": tenant_id,
            "source_fingerprints": tuple(sorted(source_fingerprints)),
            "metadata_assets": [
                asset.model_dump(mode="json") for asset in sorted(metadata_assets, key=lambda item: item.id)
            ],
            "ontology": ontology.model_dump(mode="json") if ontology else None,
            "semantic_contract_ids": tuple(sorted(semantic_contract_ids)),
        }
        fingerprint = hashlib.sha256(_canonical(values).encode()).hexdigest()
        return cls(
            **values, created_at=created_at or datetime.now(timezone.utc), content_fingerprint=fingerprint
        )


class ContextPackItem(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_id: str
    score: float = Field(ge=0)
    text: str = Field(min_length=1, max_length=20_000)
    citation: str = Field(min_length=1, max_length=512)
    certified: bool


class ContextPackRelation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str
    from_node_id: str
    to_node_id: str
    edge_type: str
    citation: str = Field(min_length=1, max_length=512)
    certified: bool = True


class ContextPack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_version: Literal["v1"] = "v1"
    snapshot_id: str
    tenant_id: str
    query: str = Field(min_length=1, max_length=4_000)
    token_budget: int = Field(gt=0, le=32_000)
    estimated_tokens: int = Field(ge=0)
    items: tuple[ContextPackItem, ...] = ()
    graph_closure: tuple[ContextPackRelation, ...] = ()
    omitted_asset_ids: tuple[str, ...] = ()
    omitted_relation_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def enforce_budget(self) -> "ContextPack":
        if self.estimated_tokens > self.token_budget:
            raise ValueError("context pack exceeds token budget")
        return self


def build_context_pack(
    snapshot: ContextSnapshot,
    results: tuple[ContextPackItem, ...],
    *,
    query: str,
    token_budget: int,
    graph_depth: int = 1,
    max_graph_edges: int = 32,
) -> ContextPack:
    """Select deterministic cited items and certified graph closure."""
    if graph_depth < 0:
        raise ValueError("graph_depth must be non-negative")
    if max_graph_edges < 0:
        raise ValueError("max_graph_edges must be non-negative")
    allowed_ids = {asset.id for asset in snapshot.metadata_assets}
    selected: list[ContextPackItem] = []
    omitted: list[str] = []
    total = 0
    for item in sorted(results, key=lambda value: (-value.score, value.asset_id)):
        if not item.certified or item.asset_id not in allowed_ids:
            omitted.append(item.asset_id)
            continue
        item_tokens = max(1, (len(item.text) + len(item.citation) + 3) // 4)
        if total + item_tokens > token_budget:
            omitted.append(item.asset_id)
            continue
        selected.append(item)
        total += item_tokens
    graph_closure: list[ContextPackRelation] = []
    omitted_relations: list[str] = []
    if snapshot.ontology and graph_depth and max_graph_edges:
        certified_nodes = {
            node.node_id for node in snapshot.ontology.nodes if node.lifecycle == "certified"
        }
        frontier = {item.asset_id for item in selected if item.asset_id in certified_nodes}
        seen_nodes = set(frontier)
        seen_edges: set[str] = set()
        for _ in range(graph_depth):
            next_frontier: set[str] = set()
            for edge in sorted(snapshot.ontology.edges, key=lambda value: value.edge_id):
                if edge.edge_id in seen_edges or not (
                    edge.from_node_id in certified_nodes and edge.to_node_id in certified_nodes
                ):
                    continue
                if edge.from_node_id not in frontier and edge.to_node_id not in frontier:
                    continue
                if len(graph_closure) >= max_graph_edges:
                    omitted_relations.append(edge.edge_id)
                    continue
                relation = ContextPackRelation(
                    edge_id=edge.edge_id, from_node_id=edge.from_node_id, to_node_id=edge.to_node_id,
                    edge_type=edge.edge_type,
                    citation=f"context:{snapshot.snapshot_id}:ontology:{edge.edge_id}",
                )
                relation_tokens = _relation_tokens(relation)
                if total + relation_tokens > token_budget:
                    omitted_relations.append(edge.edge_id)
                    continue
                graph_closure.append(relation)
                total += relation_tokens
                seen_edges.add(edge.edge_id)
                for node_id in (edge.from_node_id, edge.to_node_id):
                    if node_id not in seen_nodes:
                        next_frontier.add(node_id)
                        seen_nodes.add(node_id)
            frontier = next_frontier
            if not frontier:
                break
    return ContextPack(
        snapshot_id=snapshot.snapshot_id, tenant_id=snapshot.tenant_id, query=query,
        token_budget=token_budget, estimated_tokens=total, items=tuple(selected),
        graph_closure=tuple(graph_closure), omitted_asset_ids=tuple(omitted),
        omitted_relation_ids=tuple(omitted_relations),
    )


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _relation_tokens(relation: ContextPackRelation) -> int:
    text = " ".join((relation.from_node_id, relation.edge_type, relation.to_node_id, relation.citation))
    return max(1, (len(text) + 3) // 4)
