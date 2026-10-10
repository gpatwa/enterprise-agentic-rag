from __future__ import annotations

import json
import re
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "search"
UTC_TIMESTAMP = re.compile(r"^2026-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _load(name: str):
    with (FIXTURE_DIR / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def test_search_golden_fixture_references_and_counts_are_stable():
    documents = _load("documents.json")
    queries = _load("queries.json")
    judgments = _load("judgments.json")

    assert len(documents) == 24
    assert len({document["document_id"] for document in documents}) == 24
    assert {document["tenant_id"] for document in documents} == {
        "tenant-acme",
        "tenant-zen",
    }
    assert all(
        sum(document["tenant_id"] == tenant for document in documents) == 12
        for tenant in ("tenant-acme", "tenant-zen")
    )

    query_ids = {query["query_id"] for query in queries}
    document_ids = {document["document_id"] for document in documents}
    assert len(query_ids) == len(queries)
    assert len(queries) == 12
    assert len(judgments) >= len(queries)

    assert all(query["tenant_id"] in {"tenant-acme", "tenant-zen"} for query in queries)
    assert all(query["acl_tokens"] for query in queries)
    assert all(document["acl_tokens"] for document in documents)
    assert all(UTC_TIMESTAMP.fullmatch(document["updated_at"]) for document in documents)
    assert all(document["content_version"] == "a1" for document in documents)

    assert all(judgment["query_id"] in query_ids for judgment in judgments)
    assert all(judgment["document_id"] in document_ids for judgment in judgments)
    assert all(judgment["grade"] in {0, 1, 2, 3} for judgment in judgments)


def test_search_golden_fixture_covers_required_security_and_retrieval_cases():
    documents = _load("documents.json")
    queries = _load("queries.json")
    judgments = _load("judgments.json")

    document_by_id = {document["document_id"]: document for document in documents}
    query_by_id = {query["query_id"]: query for query in queries}
    query_texts = {query["text"] for query in queries}
    judgment_reasons = {judgment["reason"] for judgment in judgments}

    assert any("ERR_EXPORT_504" in text for text in query_texts)
    assert any("A-1001" in text for text in query_texts)
    assert any("quoted comma" in text for text in query_texts)
    assert any("429" in text for text in query_texts)
    assert any("SAML" in text for text in query_texts)
    assert "semantically relevant but ACL inaccessible" in judgment_reasons
    assert "tenant filter must exclude exact identifier from another tenant" in judgment_reasons
    assert "no relevant document" in judgment_reasons

    hidden_judgments = [
        judgment
        for judgment in judgments
        if judgment["reason"] == "semantically relevant but ACL inaccessible"
    ]
    assert len(hidden_judgments) == 1
    hidden = hidden_judgments[0]
    hidden_document = document_by_id[hidden["document_id"]]
    hidden_query = query_by_id[hidden["query_id"]]
    assert hidden["grade"] == 0
    assert hidden_document["tenant_id"] == hidden_query["tenant_id"]
    document_groups = {
        token for token in hidden_document["acl_tokens"] if not token.startswith("tenant:")
    }
    query_groups = {
        token for token in hidden_query["acl_tokens"] if not token.startswith("tenant:")
    }
    assert document_groups.isdisjoint(query_groups)

    cross_tenant = [
        judgment
        for judgment in judgments
        if judgment["reason"] == "tenant filter must exclude exact identifier from another tenant"
    ]
    assert len(cross_tenant) == 1
    assert cross_tenant[0]["grade"] == 0
