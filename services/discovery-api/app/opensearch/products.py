"""Index and search the ESCI-style product subset built by ``app.ingest`` (docs/DISCOVERY_ESCI_SCOPE.md, E3).

Products are a separate record type from experiences, so they get their own index and never touch the
experience catalog's mapping, aliases or retrieval. The index is derived: it can always be rebuilt from a
verified subset directory, and ``reconcile`` compares its document count to the subset manifest. Lexical
retrieval only; the hashing embedder is not used here.

Run: ``python -m app.opensearch.products load --subset DIR [--index NAME]`` with DISCOVERY_OPENSEARCH_URL set.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from app.config import settings_from_env
from app.ingest import IngestError, ProductRecord, verify_subset
from app.opensearch.client import OpenSearchClient, OpenSearchError

PRODUCT_INDEX_PREFIX = "discovery-products"
PRODUCT_MAPPING_VERSION = "v1"
DEFAULT_PRODUCT_INDEX = f"{PRODUCT_INDEX_PREFIX}-{PRODUCT_MAPPING_VERSION}"
BATCH_SIZE = 500
SEARCH_FIELDS = ("title^3", "brand^2", "color", "bullets", "description")


def product_mapping() -> dict[str, object]:
    """Strict mapping: an unexpected field is rejected rather than silently indexed."""
    text = {"type": "text"}
    return {
        "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {
            "dynamic": "strict",
            "_meta": {"mapping_version": PRODUCT_MAPPING_VERSION},
            "properties": {
                "product_id": {"type": "keyword"},
                "locale": {"type": "keyword"},
                "title": text,
                "description": text,
                "bullets": text,
                "brand": {"type": "text", "fields": {"raw": {"type": "keyword", "ignore_above": 255}}},
                "color": text,
            },
        },
    }


@dataclass(frozen=True)
class LoadEvidence:
    received: int
    accepted: int
    failed: tuple[str, ...]


@dataclass(frozen=True)
class Reconciliation:
    expected: int
    indexed: int

    @property
    def in_sync(self) -> bool:
        return self.expected == self.indexed


def ensure_product_index(client: OpenSearchClient, name: str = DEFAULT_PRODUCT_INDEX) -> str:
    if not client.index_exists(name):
        client.create_index(name, product_mapping())
    return name


def load_products(
    client: OpenSearchClient, records: Iterable[ProductRecord], index: str = DEFAULT_PRODUCT_INDEX
) -> LoadEvidence:
    """Upsert products by ``product_id`` in batches; re-running with the same records changes nothing."""
    ensure_product_index(client, index)
    received = accepted = 0
    failed: list[str] = []
    batch: list[tuple[str, dict[str, object]]] = []

    def flush() -> None:
        nonlocal accepted
        if not batch:
            return
        for (document_id, _), status in zip(batch, client.bulk(index, batch)):
            if status in (200, 201):
                accepted += 1
            else:
                failed.append(document_id)
        batch.clear()

    for record in records:
        received += 1
        batch.append((record.product_id, record.model_dump(mode="json")))
        if len(batch) >= BATCH_SIZE:
            flush()
    flush()
    client.refresh(index)
    return LoadEvidence(received=received, accepted=accepted, failed=tuple(failed))


def reconcile(client: OpenSearchClient, expected: int, index: str = DEFAULT_PRODUCT_INDEX) -> Reconciliation:
    return Reconciliation(expected=expected, indexed=client.count(index))


class ProductRetriever:
    """A callable ``(query, k) -> product ids`` so it plugs into ``evaluation.product_search.evaluate``."""

    def __init__(self, client: OpenSearchClient, index: str = DEFAULT_PRODUCT_INDEX) -> None:
        self._client = client
        self._index = index

    def __call__(self, query: str, k: int) -> list[str]:
        text = query.strip()
        if not text or k < 1:
            return []
        body = {
            "size": k,
            "_source": False,
            "query": {"multi_match": {"query": text, "fields": list(SEARCH_FIELDS), "type": "best_fields"}},
            "sort": ["_score", {"product_id": "asc"}],
        }
        hits = self._client.search(self._index, body).get("hits", {}).get("hits", [])
        return [str(hit["_id"]) for hit in hits]


def read_subset_records(subset_dir: Path) -> tuple[list[ProductRecord], int]:
    """Verify the subset against its manifest, then return its records and the expected count."""
    manifest = verify_subset(subset_dir)
    lines = (subset_dir / "products.jsonl").read_text(encoding="utf-8").splitlines()
    return [ProductRecord.model_validate_json(line) for line in lines if line.strip()], manifest.selected


def _client_from_env() -> OpenSearchClient | None:
    settings = settings_from_env()
    if not settings.opensearch_url:
        return None
    return OpenSearchClient(
        settings.opensearch_url,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        verify_tls=settings.opensearch_verify_tls,
        timeout=max(settings.request_timeout_seconds, 30.0),
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.opensearch.products")
    sub = parser.add_subparsers(dest="command", required=True)
    load = sub.add_parser("load", help="verify a subset and index it")
    load.add_argument("--subset", type=Path, required=True)
    load.add_argument("--index", default=DEFAULT_PRODUCT_INDEX)
    args = parser.parse_args(argv)
    client = _client_from_env()
    if client is None:
        print("DISCOVERY_OPENSEARCH_URL is not set", file=sys.stderr)
        return 2
    try:
        records, expected = read_subset_records(args.subset)
        evidence = load_products(client, records, args.index)
        result = reconcile(client, expected, args.index)
    except (IngestError, OpenSearchError) as exc:
        print(f"product load failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"index={args.index} received={evidence.received} accepted={evidence.accepted} "
        f"failed={len(evidence.failed)} indexed={result.indexed} expected={result.expected}"
    )
    return 0 if not evidence.failed and result.in_sync else 1


if __name__ == "__main__":
    raise SystemExit(main())
