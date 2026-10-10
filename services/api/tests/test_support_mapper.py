from __future__ import annotations

from datetime import datetime

import pytest


def _ticket(**overrides):
    from app.support.models import SupportTicket

    values = {
        "tenant_id": "tenant-a",
        "provider": "zendesk",
        "external_id": "42",
        "subject": "Export timeout",
        "description": "Contact jane@example.com after the export times out.",
        "status": "open",
        "priority": "high",
        "category": "incident",
        "channel": "email",
        "tags": ["export", "api"],
        "source_url": "https://support.example/tickets/42",
        "created_at": datetime(2026, 8, 20, 10, 0, 0),
        "updated_at": datetime(2026, 8, 21, 10, 0, 0),
        "updated_at_external": datetime(2026, 8, 21, 9, 0, 0),
    }
    values.update(overrides)
    return SupportTicket(**values)


def _comment(**overrides):
    from app.support.models import SupportTicketComment

    values = {
        "tenant_id": "tenant-a",
        "provider": "zendesk",
        "ticket_external_id": "42",
        "external_id": "501",
        "body_text": None,
        "body_html": "<p>Restart the <strong>export worker</strong>.</p>",
        "is_public": True,
        "created_at": datetime(2026, 8, 21, 11, 0, 0),
        "created_at_external": datetime(2026, 8, 21, 11, 0, 0),
    }
    values.update(overrides)
    return SupportTicketComment(**values)


def _article(**overrides):
    from app.support.models import SupportArticle

    values = {
        "tenant_id": "tenant-a",
        "provider": "zendesk",
        "external_id": "701",
        "title": None,
        "body_text": None,
        "body_html": None,
        "locale": None,
        "source_url": None,
        "created_at": datetime(2026, 8, 21, 12, 0, 0),
        "updated_at": datetime(2026, 8, 21, 12, 0, 0),
    }
    values.update(overrides)
    return SupportArticle(**values)


def test_ticket_mapper_is_tenant_scoped_deterministic_and_redacts_pii():
    from app.search.support_mapper import map_ticket

    first = map_ticket(_ticket(), redact_pii=True)
    second = map_ticket(_ticket(), redact_pii=True)

    assert first == second
    assert first.document_id == "tenant-a:zendesk:ticket:42"
    assert first.acl_tokens == ("tenant:tenant-a",)
    assert "jane@example.com" not in first.text
    assert "[EMAIL]" in first.text
    assert first.attributes.status == "open"
    assert first.attributes.tags == ("api", "export")
    assert first.content_version == f"sha256:{first.content_hash}"


def test_comment_mapper_normalizes_html_and_preserves_visibility_metadata():
    from app.search.support_mapper import map_comment

    document = map_comment(_comment(), redact_pii=False)

    assert document.source_type == "comment"
    assert "<strong>" not in document.text
    assert "Restart the export worker." in document.text
    assert document.metadata["is_public"] is True
    assert document.metadata["ticket_external_id"] == "42"


def test_article_mapper_has_safe_null_fallbacks():
    from app.search.support_mapper import map_article

    document = map_article(_article(), redact_pii=False)

    assert document.title == "Untitled knowledge article"
    assert "(no article content)" in document.text
    assert document.attributes.locale is None
    assert document.source_uri is None


def test_chunk_mapper_is_stable_and_keeps_parent_evidence():
    from app.search.support_mapper import map_chunk, map_ticket

    parent = map_ticket(_ticket(description="A"), redact_pii=False)
    chunk = map_chunk(parent, "Resolution step one", chunk_index=0, chunk_count=2, redact_pii=False)

    assert chunk.source_type == "ticket_chunk"
    assert chunk.source_id == "42:chunk:0"
    assert chunk.metadata["parent_document_id"] == parent.document_id
    assert chunk.metadata["chunk_index"] == 0
    assert chunk.metadata["chunk_count"] == 2
    assert chunk.acl_tokens == parent.acl_tokens
    assert chunk.permission_version == parent.permission_version


def test_chunk_mapper_rejects_invalid_position():
    from app.search.support_mapper import map_chunk, map_ticket

    parent = map_ticket(_ticket(), redact_pii=False)
    with pytest.raises(ValueError, match="chunk_index"):
        map_chunk(parent, "text", chunk_index=2, chunk_count=2)
