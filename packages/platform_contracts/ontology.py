"""Tenant-scoped ontology and provenance contracts for context construction."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ONTOLOGY_SCHEMA_VERSION = "v1"


class OntologyProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_system: str = Field(min_length=1, max_length=128)
    source_id: str = Field(min_length=1, max_length=512)
    source_version: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    fingerprint: str = Field(min_length=64, max_length=128)

    @model_validator(mode="after")
    def require_timezone(self) -> "OntologyProvenance":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("provenance observed_at must be timezone-aware")
        return self


class OntologyNode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    node_type: Literal["dataset", "field", "metric", "dimension", "entity", "policy", "glossary_term"]
    label: str = Field(min_length=1, max_length=255)
    lifecycle: Literal["candidate", "certified", "deprecated"] = "candidate"
    valid_from: datetime
    valid_to: datetime | None = None
    provenance: tuple[OntologyProvenance, ...] = Field(min_length=1)
    attributes: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_temporal_scope(self) -> "OntologyNode":
        if self.valid_from.tzinfo is None or self.valid_from.utcoffset() is None:
            raise ValueError("ontology valid_from must be timezone-aware")
        if self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("ontology valid_to must be after valid_from")
        if any(item.source_system == "" for item in self.provenance):
            raise ValueError("ontology provenance source_system must be non-empty")
        return self


class OntologyEdge(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    edge_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    edge_type: Literal["contains", "depends_on", "joins", "derived_from", "governed_by", "owned_by"]
    from_node_id: str = Field(min_length=1, max_length=255)
    to_node_id: str = Field(min_length=1, max_length=255)
    valid_from: datetime
    valid_to: datetime | None = None
    provenance: tuple[OntologyProvenance, ...] = Field(min_length=1)
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def validate_temporal_scope(self) -> "OntologyEdge":
        if self.from_node_id == self.to_node_id:
            raise ValueError("ontology edges cannot be self-referential")
        if self.valid_from.tzinfo is None or self.valid_from.utcoffset() is None:
            raise ValueError("ontology valid_from must be timezone-aware")
        if self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("ontology valid_to must be after valid_from")
        return self


class OntologySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["v1"] = ONTOLOGY_SCHEMA_VERSION
    snapshot_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    nodes: tuple[OntologyNode, ...] = ()
    edges: tuple[OntologyEdge, ...] = ()

    @model_validator(mode="after")
    def validate_graph(self) -> "OntologySnapshot":
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("ontology node IDs must be unique")
        edge_ids = {edge.edge_id for edge in self.edges}
        if len(edge_ids) != len(self.edges):
            raise ValueError("ontology edge IDs must be unique")
        if any(node.tenant_id != self.tenant_id for node in self.nodes):
            raise ValueError("ontology node tenant does not match snapshot tenant")
        if any(edge.tenant_id != self.tenant_id for edge in self.edges):
            raise ValueError("ontology edge tenant does not match snapshot tenant")
        if any(edge.from_node_id not in node_ids or edge.to_node_id not in node_ids for edge in self.edges):
            raise ValueError("ontology edge references an unknown node")
        if self.captured_at.tzinfo is None or self.captured_at.utcoffset() is None:
            raise ValueError("ontology captured_at must be timezone-aware")
        return self
