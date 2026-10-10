from datetime import datetime, timedelta, timezone

import pytest


def _scope():
    from app.search.models import SearchScope

    return SearchScope(
        tenant_id="tenant-acme",
        principal_id="agent-1",
        purpose="support-search",
        acl_tokens=("tenant:tenant-acme", "group:support"),
    )


def _result(document_id, tenant_id="tenant-acme"):
    from app.search.models import RetrievalSource, SearchResult

    return SearchResult(
        document_id=document_id,
        tenant_id=tenant_id,
        source_type="ticket",
        source_id=document_id,
        title="title",
        text="text",
        score=1.0,
        rank=1,
        retrieval_source=RetrievalSource.LEXICAL,
        metadata={"acl_tokens": [f"tenant:{tenant_id}"]},
        index_generation="g1",
        content_version="v1",
        permission_version="p1",
    )


def test_response_defense_drops_cross_tenant_results():
    from app.search.security import visible_results

    assert [item.document_id for item in visible_results([_result("a"), _result("z", "tenant-zen")], _scope())] == ["a"]


def test_interaction_events_reject_long_retention():
    from app.search.events import InteractionKind, SearchInteractionEvent

    now = datetime.now(timezone.utc)
    with pytest.raises(ValueError, match="730 days"):
        SearchInteractionEvent(
            idempotency_key="long",
            tenant_id="tenant-acme",
            principal_pseudonym="p",
            purpose="support",
            kind=InteractionKind.SEARCH,
            occurred_at=now,
            expires_at=now + timedelta(days=731),
        )


def test_audit_attributes_exclude_query_and_result_text():
    from app.search.security import safe_audit_attributes

    attrs = safe_audit_attributes(mode="hybrid", result_count=2, index_alias="alias", index_generation="g1")
    assert "query" not in attrs
    assert "text" not in attrs
