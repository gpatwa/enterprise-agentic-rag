"""Load the generated demo catalog into OpenSearch: ``python -m app.opensearch.bootstrap``.

Reads DISCOVERY_OPENSEARCH_URL (and optional DISCOVERY_OPENSEARCH_USERNAME / _PASSWORD /
_VERIFY_TLS). Safe to re-run: documents are upserted by stable ID.
"""

from __future__ import annotations

import sys

from app.config import settings_from_env
from app.demo_data import load_demo_catalog
from app.embedding import HASH_EMBEDDING_VERSION
from app.opensearch.client import OpenSearchClient, OpenSearchError
from app.opensearch.index import load_catalog
from app.search.mapping import CatalogMappingVersions


def main() -> int:
    settings = settings_from_env()
    if not settings.opensearch_url:
        print("DISCOVERY_OPENSEARCH_URL is not set", file=sys.stderr)
        return 2
    client = OpenSearchClient(
        settings.opensearch_url,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        verify_tls=settings.opensearch_verify_tls,
        timeout=max(settings.request_timeout_seconds, 30.0),
    )
    _, documents, _ = load_demo_catalog()
    versions = CatalogMappingVersions(embedding_model_version=HASH_EMBEDDING_VERSION)
    try:
        evidence = load_catalog(client, documents, versions=versions)
        indexed = client.count(versions.index_name)
    except OpenSearchError as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1
    print(
        f"index={versions.index_name} received={evidence.received} accepted={evidence.accepted} "
        f"quarantined={evidence.quarantined} indexed={indexed}"
    )
    return 0 if evidence.quarantined == 0 and indexed == evidence.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
