from __future__ import annotations

import pytest


def _scope(**overrides):
    values = {
        "tenant_id": "tenant-acme",
        "principal_id": "user-1",
        "purpose": "test",
        "acl_tokens": ["tenant:tenant-acme", "group:support"],
    }
    values.update(overrides)
    return values


def _document(document_id: str, *, tenant_id: str = "tenant-acme", acl_tokens=None, title: str = "Export timeout", status: str = "open"):
    from app.search.models import SearchDocument

    return SearchDocument(
        document_id=document_id,
        tenant_id=tenant_id,
        source_type="ticket",
        source_id=document_id,
        provider="test",
        title=title,
        text=f"{title}. Retry the export worker.",
        metadata={"status": status, "tags": ["export"]},
        acl_tokens=acl_tokens or [f"tenant:{tenant_id}", "group:support"],
        content_version="v1",
        permission_version="acl-v1",
    )


@pytest.mark.asyncio
async def test_fake_provider_is_deterministic_and_enforces_tenant_acl_and_filters():
    from tests.fakes.search_provider import InMemorySearchProvider

    from app.search.models import SearchIndexSpec, SearchRequest

    provider = InMemorySearchProvider()
    await provider.connect()
    await provider.ensure_index(
        SearchIndexSpec(
            alias="support-search",
            generation="support-v1",
            schema_version="schema-v1",
            vector_dimensions=3,
            embedding_model_version="test-v1",
        )
    )
    await provider.activate_alias("support-search", "support-v1")
    await provider.upsert(
        [
            _document("doc-b"),
            _document("doc-a"),
            _document("doc-private", acl_tokens=["tenant:tenant-acme", "group:finance"]),
            _document("doc-other", tenant_id="tenant-zen"),
        ]
    )

    request = SearchRequest(
        text="export timeout",
        scope=_scope(),
        filters=[{"field": "status", "value": "open"}],
        limit=10,
    )
    first = await provider.search(request)
    second = await provider.search(request)

    assert first == second
    assert [result.document_id for result in first.results] == ["doc-a", "doc-b"]
    assert all(result.tenant_id == "tenant-acme" for result in first.results)
    assert first.index_generation == "support-v1"
    assert first.results[0].explanation is not None


@pytest.mark.asyncio
async def test_fake_provider_delete_is_tenant_scoped_and_idempotent():
    from tests.fakes.search_provider import InMemorySearchProvider

    from app.search.models import SearchIndexSpec, SearchRequest, SearchScope

    provider = InMemorySearchProvider()
    await provider.ensure_index(
        SearchIndexSpec(
            alias="support-search",
            generation="support-v1",
            schema_version="schema-v1",
            vector_dimensions=3,
            embedding_model_version="test-v1",
        )
    )
    await provider.activate_alias("support-search", "support-v1")
    await provider.upsert([_document("same-id"), _document("same-id", tenant_id="tenant-zen")])

    scope = SearchScope(**_scope())
    result = await provider.delete(["same-id"], scope=scope)
    assert result.attempted == 1
    assert result.succeeded == 1

    remaining = await provider.search(SearchRequest(text="export timeout", scope=scope))
    assert remaining.results == ()
