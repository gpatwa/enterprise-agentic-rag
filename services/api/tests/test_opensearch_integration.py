"""Service-level OpenSearch checks; never make unit CI depend on a cluster."""

import os

import pytest

pytestmark = pytest.mark.opensearch_integration


@pytest.mark.asyncio
async def test_local_opensearch_health_when_explicitly_enabled():
    if os.getenv("OPENSEARCH_INTEGRATION", "").lower() not in {"1", "true", "yes"}:
        pytest.skip("set OPENSEARCH_INTEGRATION=1 to run against the local OpenSearch profile")

    from app.config import settings
    from app.search.models import SearchIndexSpec
    from app.search.opensearch import OpenSearchProvider
    from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION

    provider = OpenSearchProvider(config=settings)
    await provider.connect()
    try:
        generation = "opensearch-integration-g1"
        await provider.ensure_index(
            SearchIndexSpec(
                alias=settings.OPENSEARCH_INDEX_ALIAS,
                generation=generation,
                schema_version=SUPPORT_SEARCH_SCHEMA_VERSION,
                vector_dimensions=settings.OPENSEARCH_VECTOR_DIMENSIONS,
                embedding_model_version=settings.OPENSEARCH_EMBEDDING_MODEL_VERSION,
            )
        )
        await provider.activate_alias(settings.OPENSEARCH_INDEX_ALIAS, generation)
        health = await provider.health()
        assert health.status == "ready"
        assert health.index_generation == generation
    finally:
        await provider.close()
