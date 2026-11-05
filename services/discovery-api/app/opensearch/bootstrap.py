"""Load the generated demo catalog into OpenSearch: ``python -m app.opensearch.bootstrap``.

Reads DISCOVERY_OPENSEARCH_URL (and optional DISCOVERY_OPENSEARCH_USERNAME / _PASSWORD /
_VERIFY_TLS). Safe to re-run: documents are upserted by stable ID.
"""

from __future__ import annotations

import argparse
import sys

from app.config import settings_from_env
from app.demo_data import load_demo_catalog
from app.embedding import create_embedder
from app.opensearch.client import OpenSearchClient, OpenSearchError
from app.opensearch.index import load_catalog
from app.search.mapping import CatalogMappingVersions


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.opensearch.bootstrap")
    parser.add_argument(
        "--confirm-spend",
        action="store_true",
        help="allow calls to a billable embedding service (required when DISCOVERY_EMBEDDING_PROVIDER=azure_openai)",
    )
    args = parser.parse_args(argv)
    settings = settings_from_env()
    if not settings.opensearch_url:
        print("DISCOVERY_OPENSEARCH_URL is not set", file=sys.stderr)
        return 2
    embedder = create_embedder(settings)
    experiences, _, _ = load_demo_catalog()
    if getattr(embedder, "is_billable", False):
        texts = len(experiences)
        requests = -(-texts // 16)
        print(
            f"embedding provider {embedder.model_version}: {texts} texts in about {requests} requests "
            f"(a model call; cost not computed here; cap {settings.embedding_max_texts} texts per process)"
        )
        if not args.confirm_spend:
            print("not calling the service: pass --confirm-spend to proceed", file=sys.stderr)
            return 2
    client = OpenSearchClient(
        settings.opensearch_url,
        username=settings.opensearch_username,
        password=settings.opensearch_password,
        verify_tls=settings.opensearch_verify_tls,
        timeout=max(settings.request_timeout_seconds, 30.0),
    )
    try:
        _, documents, _ = load_demo_catalog(embedder=embedder)
        versions = CatalogMappingVersions(
            embedding_model_version=embedder.model_version, embedding_dimensions=embedder.dimensions
        )
        evidence = load_catalog(client, documents, versions=versions)
        indexed = client.count(versions.index_name)
    except OpenSearchError as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # embedding failures: report the type and message, never the input
        print(f"bootstrap failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        f"index={versions.index_name} received={evidence.received} accepted={evidence.accepted} "
        f"quarantined={evidence.quarantined} indexed={indexed}"
    )
    return 0 if evidence.quarantined == 0 and indexed == evidence.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
