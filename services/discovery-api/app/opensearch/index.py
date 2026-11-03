"""Create the versioned catalog index and load documents through the bounded indexing worker."""

from __future__ import annotations

from typing import Iterable

from app.indexing.worker import (
    BulkIndexProvider,
    BulkIndexRequest,
    BulkIndexResult,
    IndexingEvidence,
    IndexingWorker,
)
from app.opensearch.client import OpenSearchClient, OpenSearchUnavailable
from app.search.mapper import CatalogSearchDocument
from app.search.mapping import CATALOG_INDEX_PREFIX, CatalogMappingVersions, generate_catalog_mapping

READ_ALIAS = f"{CATALOG_INDEX_PREFIX}-read"
WRITE_ALIAS = f"{CATALOG_INDEX_PREFIX}-write"


def ensure_catalog_index(client: OpenSearchClient, versions: CatalogMappingVersions | None = None) -> str:
    """Create the generation's index if absent and return its name.

    The read and write aliases are attached only when they do not exist yet. A later generation is
    built unaliased and promoted by an explicit, validated alias swap (see indexing/maintenance.py).
    """
    versions = versions or CatalogMappingVersions()
    name = versions.index_name
    if client.index_exists(name):
        return name
    mapping = generate_catalog_mapping(versions)
    body: dict[str, object] = {
        "settings": mapping["settings"],
        "mappings": {**mapping["mappings"], "_meta": mapping["_meta"]},
    }
    if not any(client.alias_exists(alias) for alias in mapping["aliases"]):
        body["aliases"] = mapping["aliases"]
    client.create_index(name, body)
    return name


class OpenSearchBulkProvider:
    """Idempotent upserts keyed by the stable exposure key; implements the worker's provider boundary."""

    def __init__(self, client: OpenSearchClient, index: str = WRITE_ALIAS) -> None:
        self._client = client
        self._index = index

    def bulk_upsert(self, requests: tuple[BulkIndexRequest, ...]) -> BulkIndexResult:
        try:
            statuses = self._client.bulk(self._index, [(item.document_id, item.document) for item in requests])
        except OpenSearchUnavailable:
            return BulkIndexResult(transient_ids=tuple(item.document_id for item in requests))
        accepted: list[str] = []
        failed: list[str] = []
        transient: list[str] = []
        for item, status in zip(requests, statuses):
            if status in (200, 201):
                accepted.append(item.document_id)
            elif status == 429 or status >= 500:
                transient.append(item.document_id)
            else:
                failed.append(item.document_id)
        return BulkIndexResult(accepted_ids=tuple(accepted), failed_ids=tuple(failed), transient_ids=tuple(transient))


def bulk_requests(documents: Iterable[CatalogSearchDocument], *, start: int = 0) -> tuple[BulkIndexRequest, ...]:
    return tuple(
        BulkIndexRequest(
            checkpoint=start + position,
            tenant_id=document.tenant_id,
            document_id=document.exposure_key,
            document=document.model_dump(mode="json"),
            document_version=document.content_version,
        )
        for position, document in enumerate(documents, start=1)
    )


def load_catalog(
    client: OpenSearchClient,
    documents: Iterable[CatalogSearchDocument],
    *,
    versions: CatalogMappingVersions | None = None,
    provider: BulkIndexProvider | None = None,
) -> IndexingEvidence:
    """Ensure the index exists, index every document, refresh, and return the worker's evidence."""
    name = ensure_catalog_index(client, versions)
    # Write to the generation by name so a rebuild never lands in whichever index the alias currently serves.
    worker = IndexingWorker(provider or OpenSearchBulkProvider(client, name), base_backoff_seconds=0.1)
    evidence = worker.run(bulk_requests(documents))
    client.refresh(name)
    return evidence
