from __future__ import annotations

from types import SimpleNamespace

import pytest


def _config(**overrides):
    values = {
        "OPENSEARCH_ENABLED": True,
        "OPENSEARCH_URL": "http://localhost:9200",
        "ENV": "dev",
        "OPENSEARCH_AUTH_MODE": "none",
    }
    values.update(overrides)
    return SimpleNamespace(
        **values,
        validate_opensearch_settings=lambda: None,
    )


def test_unknown_provider_fails_without_importing_a_backend(monkeypatch):
    from app.search import factory

    imported = []
    monkeypatch.setattr(factory, "import_module", lambda name: imported.append(name))

    with pytest.raises(ValueError, match="Unknown enterprise search provider"):
        factory.create_search_provider("qdrant", config=_config())

    assert imported == []


def test_opensearch_provider_is_not_imported_when_disabled(monkeypatch):
    from app.search import factory

    imported = []
    monkeypatch.setattr(factory, "import_module", lambda name: imported.append(name))

    with pytest.raises(RuntimeError, match="disabled"):
        factory.create_search_provider("opensearch", config=_config(OPENSEARCH_ENABLED=False))

    assert imported == []


def test_opensearch_provider_is_imported_lazily_and_constructed(monkeypatch):
    from app.search import factory

    config = _config()
    constructed = []

    class FakeOpenSearchProvider:
        def __init__(self, *, config):
            constructed.append(config)

    monkeypatch.setattr(
        factory,
        "import_module",
        lambda name: SimpleNamespace(OpenSearchProvider=FakeOpenSearchProvider),
    )

    provider = factory.create_search_provider(" OpenSearch ", config=config)

    assert isinstance(provider, FakeOpenSearchProvider)
    assert constructed == [config]


def test_missing_lazy_provider_class_fails_with_actionable_error(monkeypatch):
    from app.search import factory

    monkeypatch.setattr(factory, "import_module", lambda name: SimpleNamespace())

    with pytest.raises(RuntimeError, match="does not expose OpenSearchProvider"):
        factory.create_search_provider("opensearch", config=_config())
