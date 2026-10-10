from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError


def _document(**overrides):
    values = {
        "document_id": "doc-1",
        "tenant_id": "tenant-acme",
        "source_type": "ticket",
        "source_id": "A-1001",
        "provider": "zendesk",
        "title": "Export timeout",
        "text": "The export timed out.",
        "acl_tokens": ["tenant:tenant-acme", "group:support"],
        "content_version": "content-v1",
        "permission_version": "acl-v1",
        "embedding_model_version": "embed-v1",
        "content_hash": "a" * 64,
        "updated_at": datetime(2026, 8, 22, tzinfo=timezone.utc),
        "created_at": datetime(2026, 8, 20, tzinfo=timezone.utc),
        "attributes": {"status": "open", "tags": ["export", "timeout"]},
        "rank_features": {"freshness_score": 0.9, "quality_score": 0.8},
    }
    values.update(overrides)
    return values


def test_support_search_document_has_versioned_typed_fields():
    from app.search.schema import SUPPORT_SEARCH_SCHEMA_VERSION, SupportSearchDocument

    document = SupportSearchDocument(**_document())

    assert document.schema_version == SUPPORT_SEARCH_SCHEMA_VERSION
    assert document.attributes.tags == ("export", "timeout")
    assert document.rank_features.freshness_score == 0.9
    assert document.permission_version == "acl-v1"
    assert set(document.model_dump()) >= {
        "schema_version",
        "attributes",
        "rank_features",
        "created_at",
        "updated_at",
        "content_hash",
        "vector",
    }


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"schema_version": "support-search-v2"}, "unsupported"),
        ({"content_hash": "g" * 64}, "SHA-256"),
        ({"acl_tokens": ["group:support"]}, "tenant scope"),
        ({"rank_features": {"quality_score": 1.5}}, "less than or equal to 1"),
        ({"rank_features": {"popularity_score": -1}}, "greater than or equal to 0"),
    ],
)
def test_support_search_document_rejects_invalid_version_acl_and_features(overrides, message):
    from app.search.schema import SupportSearchDocument

    with pytest.raises(ValidationError, match=message):
        SupportSearchDocument(**_document(**overrides))
