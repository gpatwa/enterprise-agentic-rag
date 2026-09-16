"""OpenSearch context index adapter with provider-owned scope filters."""
from __future__ import annotations

import json
from typing import Any, Protocol

from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot


class ContextSearchClient(Protocol):
    def put(self, url: str, *, json: dict[str, Any]) -> Any:
        ...

    def post(
        self, url: str, *, json: dict[str, Any] | None = None,
        content: str | None = None, headers: dict[str, str] | None = None,
    ) -> Any:
        ...


def build_context_index_mapping() -> dict[str, Any]:
    return {
        "mappings": {"properties": {
            "tenant_id": {"type": "keyword"}, "snapshot_id": {"type": "keyword"},
            "asset_id": {"type": "keyword"}, "lifecycle": {"type": "keyword"},
            "certified": {"type": "boolean"}, "text": {"type": "text"},
            "source_version": {"type": "keyword"}, "source_fingerprints": {"type": "keyword"},
        }}
    }


class OpenSearchContextIndex:
    """Small synchronous adapter; all authorization filters are provider-owned."""

    def __init__(self, base_url: str, index_name: str, client: ContextSearchClient):
        self.base_url = base_url.rstrip("/")
        self.index_name = index_name
        self.client = client

    def create_index(self) -> None:
        response = self.client.put(
            f"{self.base_url}/{self.index_name}", json=build_context_index_mapping()
        )
        response.raise_for_status()

    def index_snapshot(self, snapshot: ContextSnapshot) -> int:
        documents = [self._document(snapshot, asset) for asset in snapshot.metadata_assets]
        if documents:
            operations: list[str] = []
            for document in documents:
                operations.append(json.dumps(
                    {"index": {"_index": self.index_name, "_id": self._document_id(document)}},
                    separators=(",", ":"),
                ))
                operations.append(json.dumps(document, separators=(",", ":")))
            response = self.client.post(
                f"{self.base_url}/_bulk", content="\n".join(operations) + "\n",
                headers={"content-type": "application/x-ndjson"},
            )
            response.raise_for_status()
        return len(documents)

    def search(
        self, query: str, *, tenant_id: str, certified_only: bool = True, limit: int = 10
    ) -> tuple[ContextPackItem, ...]:
        filters: list[dict[str, Any]] = [{"term": {"tenant_id": tenant_id}}]
        if certified_only:
            filters.append({"term": {"certified": True}})
        body = {
            "size": limit,
            "query": {"bool": {"must": [{"multi_match": {"query": query, "fields": ["text", "asset_id"]}}], "filter": filters}},
            "_source": ["asset_id", "snapshot_id", "text", "certified", "tenant_id"],
        }
        response = self.client.post(f"{self.base_url}/{self.index_name}/_search", json=body)
        response.raise_for_status()
        hits = response.json().get("hits", {}).get("hits", [])
        return tuple(
            ContextPackItem(
                asset_id=str(hit.get("_source", {}).get("asset_id", hit.get("_id", ""))),
                score=float(hit.get("_score", 0)), text=str(hit.get("_source", {}).get("text", "")),
                citation=f"context:{hit.get('_source', {}).get('snapshot_id', 'unknown')}",
                certified=bool(hit.get("_source", {}).get("certified", False)),
            )
            for hit in hits
            if hit.get("_source", {}).get("tenant_id") == tenant_id
            and (not certified_only or bool(hit.get("_source", {}).get("certified", False)))
        )

    @staticmethod
    def _document_id(document: dict[str, Any]) -> str:
        return ":".join((document["tenant_id"], document["snapshot_id"], document["asset_id"]))

    @staticmethod
    def _document(snapshot: ContextSnapshot, asset: Any) -> dict[str, Any]:
        text = " ".join(
            [asset.display_name, asset.physical_name, asset.description or "", *asset.tags]
            + [column.name + " " + (column.description or "") for column in asset.columns]
        )
        return {
            "tenant_id": snapshot.tenant_id, "snapshot_id": snapshot.snapshot_id, "asset_id": asset.id,
            "lifecycle": "certified" if asset.certified else "candidate", "certified": asset.certified,
            "text": text, "source_version": asset.source_version,
            "source_fingerprints": list(snapshot.source_fingerprints),
        }
