from __future__ import annotations

from importlib import import_module
from typing import Any

from app.config import Settings, settings

SUPPORTED_SEARCH_PROVIDERS = ("opensearch",)


def create_search_provider(provider: str, *, config: Settings | None = None) -> Any:
    """Create an enterprise search provider without importing providers eagerly.

    The legacy Qdrant VectorDB path is intentionally outside this factory. The
    pre-customer launch does not require a Qdrant compatibility adapter.
    """
    normalized = provider.strip().lower()
    if normalized != "opensearch":
        supported = ", ".join(SUPPORTED_SEARCH_PROVIDERS)
        raise ValueError(
            f"Unknown enterprise search provider: '{provider}'. Supported: {supported}. "
            "Qdrant is a separate local/demo fixture and is not a supported enterprise provider."
        )

    active_config = config or settings
    if not active_config.OPENSEARCH_ENABLED:
        raise RuntimeError("OpenSearch provider is disabled; set OPENSEARCH_ENABLED=true after the rollout gate")
    active_config.validate_opensearch_settings()

    # OS-013 supplies this module. Keeping the import here makes the default
    # API process independent of the optional provider implementation.
    provider_module = import_module("app.search.opensearch")
    provider_class = getattr(provider_module, "OpenSearchProvider", None)
    if provider_class is None:
        raise RuntimeError("OpenSearch provider module does not expose OpenSearchProvider")
    return provider_class(config=active_config)
