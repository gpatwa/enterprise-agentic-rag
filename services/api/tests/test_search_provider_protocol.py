from __future__ import annotations

from collections.abc import Sequence


class ConformingProvider:
    async def connect(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def health(self):
        return None

    async def ensure_index(self, spec):
        return None

    async def activate_alias(self, alias: str, index_name: str) -> None:
        return None

    async def upsert(self, documents: Sequence, *, index: str | None = None):
        return None

    async def delete(self, document_ids: Sequence[str], *, scope, index: str | None = None):
        return None

    async def search(self, request):
        return None


class MissingSearchMethod:
    async def connect(self) -> None:
        return None


def test_enterprise_search_provider_is_runtime_checkable():
    from app.search.base import EnterpriseSearchProvider

    assert isinstance(ConformingProvider(), EnterpriseSearchProvider)
    assert not isinstance(MissingSearchMethod(), EnterpriseSearchProvider)


def test_enterprise_search_provider_exposes_required_operations():
    from app.search.base import EnterpriseSearchProvider

    required = {
        "connect",
        "close",
        "health",
        "ensure_index",
        "activate_alias",
        "upsert",
        "delete",
        "search",
    }
    assert required.issubset(set(EnterpriseSearchProvider.__dict__))
