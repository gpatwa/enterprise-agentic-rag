import pytest


@pytest.mark.asyncio
async def test_search_audit_writes_only_redacted_summary(monkeypatch):
    from app.search import audit
    from app.search.models import SearchMode, SearchRequest, SearchResponse, SearchScope

    captured = {}

    async def fake_log_event(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(audit, "log_event", fake_log_event)
    request = SearchRequest(
        text="private customer issue",
        scope=SearchScope(
            tenant_id="tenant-acme", principal_id="agent-1", purpose="support", acl_tokens=("tenant:tenant-acme",)
        ),
        mode=SearchMode.LEXICAL,
        request_id="req-1",
    )
    await audit.record_search_audit(
        request,
        SearchResponse(index_alias="alias", index_generation="g1"),
        success=True,
        status_code=200,
    )
    assert captured["pii_redacted"] is True
    assert "private customer issue" not in str(captured)
    assert captured["extra"]["result_count"] == 0
