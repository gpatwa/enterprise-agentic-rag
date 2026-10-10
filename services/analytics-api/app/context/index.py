"""OpenSearch context index adapter with provider-owned scope filters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot
from packages.platform_contracts.ontology import OntologyNode

ONTOLOGY_DOC_TYPE = "ontology_node"


class ContextSearchClient(Protocol):
    def head(self, url: str) -> Any: ...

    def put(self, url: str, *, json: dict[str, Any]) -> Any: ...

    def post(
        self,
        url: str,
        *,
        json: dict[str, Any] | None = None,
        content: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Any: ...


@dataclass(frozen=True)
class OntologySearchHit:
    node_id: str
    node_type: str
    label: str
    lifecycle: str
    score: float
    citation: str


def _mapping_properties() -> dict[str, Any]:
    return {
        "tenant_id": {"type": "keyword"},
        "snapshot_id": {"type": "keyword"},
        "asset_id": {"type": "keyword"},
        "lifecycle": {"type": "keyword"},
        "certified": {"type": "boolean"},
        "text": {"type": "text"},
        "source_version": {"type": "keyword"},
        "source_fingerprints": {"type": "keyword"},
        "doc_type": {"type": "keyword"},
        "node_type": {"type": "keyword"},
        "label": {"type": "text"},
    }


def build_context_index_mapping() -> dict[str, Any]:
    return {"mappings": {"properties": _mapping_properties()}}


class OpenSearchContextIndex:
    """Small synchronous adapter; all authorization filters are provider-owned."""

    def __init__(self, base_url: str, index_name: str, client: ContextSearchClient):
        self.base_url = base_url.rstrip("/")
        self.index_name = index_name
        self.client = client

    def create_index(self) -> None:
        response = self.client.put(f"{self.base_url}/{self.index_name}", json=build_context_index_mapping())
        response.raise_for_status()

    def ensure_index(self) -> None:
        response = self.client.head(f"{self.base_url}/{self.index_name}")
        if response.status_code == 200:
            # Additive and idempotent: an index created before ontology support gains the
            # keyword fields instead of having them dynamically mapped as analyzed text.
            update = self.client.put(
                f"{self.base_url}/{self.index_name}/_mapping", json={"properties": _mapping_properties()}
            )
            update.raise_for_status()
            return
        if response.status_code != 404:
            response.raise_for_status()
        self.create_index()

    def index_snapshot(self, snapshot: ContextSnapshot) -> int:
        documents = [self._document(snapshot, asset) for asset in snapshot.metadata_assets]
        if snapshot.ontology:
            documents.extend(
                self._ontology_document(snapshot, node)
                for node in sorted(snapshot.ontology.nodes, key=lambda item: item.node_id)
            )
        if documents:
            operations: list[str] = []
            for document in documents:
                operations.append(
                    json.dumps(
                        {"index": {"_index": self.index_name, "_id": self._document_id(document)}},
                        separators=(",", ":"),
                    )
                )
                operations.append(json.dumps(document, separators=(",", ":")))
            response = self.client.post(
                f"{self.base_url}/_bulk",
                content="\n".join(operations) + "\n",
                headers={"content-type": "application/x-ndjson"},
            )
            response.raise_for_status()
        return len(documents)

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        snapshot_id: str | None = None,
        certified_only: bool = True,
        limit: int = 10,
    ) -> tuple[ContextPackItem, ...]:
        filters: list[dict[str, Any]] = [{"term": {"tenant_id": tenant_id}}]
        if snapshot_id:
            filters.append({"term": {"snapshot_id": snapshot_id}})
        if certified_only:
            filters.append({"term": {"certified": True}})
        body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": ["text", "asset_id"]}}],
                    "filter": filters,
                    # Ontology documents have their own search; they are not metadata assets.
                    "must_not": [{"term": {"doc_type": ONTOLOGY_DOC_TYPE}}],
                }
            },
            "_source": ["asset_id", "snapshot_id", "text", "certified", "tenant_id", "doc_type"],
        }
        response = self.client.post(f"{self.base_url}/{self.index_name}/_search", json=body)
        response.raise_for_status()
        hits = response.json().get("hits", {}).get("hits", [])
        return tuple(
            ContextPackItem(
                asset_id=str(hit.get("_source", {}).get("asset_id", hit.get("_id", ""))),
                score=float(hit.get("_score", 0)),
                text=str(hit.get("_source", {}).get("text", "")),
                citation=f"context:{hit.get('_source', {}).get('snapshot_id', 'unknown')}",
                certified=bool(hit.get("_source", {}).get("certified", False)),
            )
            for hit in hits
            if hit.get("_source", {}).get("tenant_id") == tenant_id
            and hit.get("_source", {}).get("doc_type") != ONTOLOGY_DOC_TYPE
            and (snapshot_id is None or hit.get("_source", {}).get("snapshot_id") == snapshot_id)
            and (not certified_only or bool(hit.get("_source", {}).get("certified", False)))
        )

    def search_ontology(
        self,
        query: str,
        *,
        tenant_id: str,
        snapshot_id: str,
        certified_only: bool = True,
        node_types: tuple[str, ...] = (),
        limit: int = 10,
    ) -> tuple[OntologySearchHit, ...]:
        """Find ontology nodes by label, alias, or description within one snapshot.

        Discovery only: resolution stays an exact lookup against the snapshot's graph.
        Scope filters are provider-owned and re-checked on every hit.
        """
        filters: list[dict[str, Any]] = [
            {"term": {"tenant_id": tenant_id}},
            {"term": {"snapshot_id": snapshot_id}},
            {"term": {"doc_type": ONTOLOGY_DOC_TYPE}},
        ]
        if certified_only:
            filters.append({"term": {"certified": True}})
        if node_types:
            filters.append({"terms": {"node_type": list(node_types)}})
        body = {
            "size": limit,
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": ["text", "label^2", "asset_id"]}}],
                    "filter": filters,
                }
            },
            "_source": ["asset_id", "snapshot_id", "node_type", "label", "lifecycle", "certified", "tenant_id", "doc_type"],
        }
        response = self.client.post(f"{self.base_url}/{self.index_name}/_search", json=body)
        response.raise_for_status()
        hits = []
        for hit in response.json().get("hits", {}).get("hits", []):
            source = hit.get("_source", {})
            if (
                source.get("tenant_id") != tenant_id
                or source.get("snapshot_id") != snapshot_id
                or source.get("doc_type") != ONTOLOGY_DOC_TYPE
                or (certified_only and source.get("lifecycle") != "certified")
                or (node_types and source.get("node_type") not in node_types)
            ):
                continue
            hits.append(
                OntologySearchHit(
                    node_id=str(source.get("asset_id", hit.get("_id", ""))),
                    node_type=str(source.get("node_type", "")),
                    label=str(source.get("label", "")),
                    lifecycle=str(source.get("lifecycle", "")),
                    score=float(hit.get("_score", 0)),
                    citation=f"context:{snapshot_id}:ontology:{source.get('asset_id', '')}",
                )
            )
        return tuple(hits)

    @staticmethod
    def _document_id(document: dict[str, Any]) -> str:
        parts = [document["tenant_id"], document["snapshot_id"]]
        if document.get("doc_type") == ONTOLOGY_DOC_TYPE:
            parts.append(ONTOLOGY_DOC_TYPE)  # node IDs may equal asset IDs
        parts.append(document["asset_id"])
        return ":".join(parts)

    @staticmethod
    def _ontology_document(snapshot: ContextSnapshot, node: OntologyNode) -> dict[str, Any]:
        attributes = node.attributes
        aliases = [
            str(value)
            for key in ("aliases", "synonyms")
            for value in (attributes.get(key) if isinstance(attributes.get(key), (list, tuple)) else [])
        ]
        description = attributes.get("description")
        text = " ".join([node.label, node.node_type, *aliases, description if isinstance(description, str) else ""])
        return {
            "tenant_id": snapshot.tenant_id,
            "snapshot_id": snapshot.snapshot_id,
            "asset_id": node.node_id,
            "doc_type": ONTOLOGY_DOC_TYPE,
            "node_type": node.node_type,
            "label": node.label,
            "lifecycle": node.lifecycle,
            "certified": node.lifecycle == "certified",
            "text": text.strip(),
            "source_version": node.provenance[0].source_version,
            "source_fingerprints": list(snapshot.source_fingerprints),
        }

    @staticmethod
    def _document(snapshot: ContextSnapshot, asset: Any) -> dict[str, Any]:
        text = " ".join(
            [asset.display_name, asset.physical_name, asset.description or "", *asset.tags]
            + [column.name + " " + (column.description or "") for column in asset.columns]
        )
        return {
            "tenant_id": snapshot.tenant_id,
            "snapshot_id": snapshot.snapshot_id,
            "asset_id": asset.id,
            "lifecycle": "certified" if asset.certified else "candidate",
            "certified": asset.certified,
            "text": text,
            "source_version": asset.source_version,
            "source_fingerprints": list(snapshot.source_fingerprints),
        }
