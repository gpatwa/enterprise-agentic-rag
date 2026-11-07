"""RO-5: chat retrieval can read file chunks from OpenSearch behind the rollout flags (fakes only)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from app.agents.nodes import retriever
from app.config import settings
from app.search.models import SearchMode


class FakeQdrant:
    def __init__(self, texts=("q one", "q two"), fail=False):
        self.texts, self.fail, self.calls = texts, fail, 0

    async def search(self, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError("qdrant down")
        return [{"payload": {"text": t, "filename": "q.pdf"}} for t in self.texts]


class FakeGraph:
    async def query_related(self, **kwargs):
        return []


class FakeSearch:
    def __init__(self, texts=("o one", "q one"), fail=False, tenant=None, delay=0.0):
        self.texts, self.fail, self.tenant, self.requests, self.delay = texts, fail, tenant, [], delay

    async def search(self, request):
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("opensearch down")
        tenant = self.tenant or request.scope.tenant_id
        results = [SimpleNamespace(tenant_id=tenant, text=t, metadata={"filename": "o.pdf"}) for t in self.texts]
        return SimpleNamespace(results=results)


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(settings, "OPENSEARCH_ENABLED", True)
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 0)
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_ENABLED", False)
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_PERCENT", 0)
    monkeypatch.setattr(settings, "OPENSEARCH_ROLLBACK", False)
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_TENANTS", "")
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_TENANTS", "")
    monkeypatch.setattr(settings, "OPENSEARCH_RETRIEVAL_TIMEOUT_SECONDS", 1.5)
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", False)
    monkeypatch.setattr(settings, "MULTIMODAL_ENABLED", False)
    yield
    retriever.set_search_service(None)
    retriever.set_clients(None, None)


async def _run(qdrant, search, tenant="acme"):
    retriever.set_clients(qdrant, FakeGraph())
    retriever.set_search_service(search)
    state = {"current_query": "reset password", "query_embedding": [0.1, 0.2, 0.3]}
    out = await retriever.retrieve_node(state, {"configurable": {"tenant_id": tenant}})
    return out["documents"]


async def test_default_is_qdrant_only_and_never_touches_opensearch() -> None:
    search = FakeSearch()
    docs = await _run(FakeQdrant(), search)
    assert docs == ["q one [Source: q.pdf]", "q two [Source: q.pdf]"] and search.requests == []


async def test_no_search_service_means_qdrant_even_at_100_percent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    docs = await _run(FakeQdrant(), None)
    assert docs[0].startswith("q one")


async def test_canary_tenant_reads_opensearch_with_a_tenant_scoped_hybrid_chunk_query(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    qdrant, search = FakeQdrant(), FakeSearch()
    docs = await _run(qdrant, search)
    assert docs == ["o one [Source: o.pdf]", "q one [Source: o.pdf]"] and qdrant.calls == 0
    (request,) = search.requests
    assert request.mode is SearchMode.HYBRID and request.query_vector == (0.1, 0.2, 0.3)
    assert request.scope.tenant_id == "acme" and request.scope.acl_tokens == ("tenant:acme",)
    assert [(f.field, f.value) for f in request.filters] == [("source_type", "file_chunk")]


async def test_a_tenant_outside_the_canary_stays_on_qdrant(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 1)
    from app.search.rollout import rollout_bucket

    outside = next(t for t in (f"t{i}" for i in range(500)) if rollout_bucket(t) >= 1)
    search = FakeSearch()
    docs = await _run(FakeQdrant(), search, tenant=outside)
    assert docs[0].startswith("q one") and search.requests == []


async def test_rollback_forces_qdrant_even_at_100_percent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    monkeypatch.setattr(settings, "OPENSEARCH_ROLLBACK", True)
    search = FakeSearch()
    docs = await _run(FakeQdrant(), search)
    assert docs[0].startswith("q one") and search.requests == []


async def test_opensearch_failure_falls_back_to_qdrant(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    docs = await _run(FakeQdrant(), FakeSearch(fail=True))
    assert docs == ["q one [Source: q.pdf]", "q two [Source: q.pdf]"]


async def test_results_from_another_tenant_are_dropped(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    assert await _run(FakeQdrant(), FakeSearch(tenant="someone-else")) == []


async def test_single_tenant_mode_queries_the_default_tenant(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    monkeypatch.setattr(settings, "SINGLE_TENANT_MODE", True)
    search = FakeSearch()
    await _run(FakeQdrant(), search, tenant="whatever")
    assert search.requests[0].scope.tenant_id == "default"


async def test_shadow_returns_qdrants_answer_and_logs_overlap_without_text(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_PERCENT", 100)
    search = FakeSearch()
    with caplog.at_level(logging.INFO, logger=retriever.logger.name):
        docs = await _run(FakeQdrant(texts=("q one", "q two")), search)
    assert docs == ["q one [Source: q.pdf]", "q two [Source: q.pdf]"] and len(search.requests) == 1
    line = next(r.getMessage() for r in caplog.records if "Retrieval shadow" in r.getMessage())
    assert "qdrant=2" in line and "opensearch=2" in line and "overlap=" in line and "o one" not in line


async def test_shadow_failure_never_changes_the_reply(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_PERCENT", 100)
    docs = await _run(FakeQdrant(), FakeSearch(fail=True))
    assert docs == ["q one [Source: q.pdf]", "q two [Source: q.pdf]"]


async def test_a_named_canary_tenant_is_served_from_opensearch_at_zero_percent(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_TENANTS", " default , other ")
    search = FakeSearch()
    docs = await _run(FakeQdrant(), search, tenant="default")
    assert docs[0] == "o one [Source: o.pdf]" and len(search.requests) == 1
    outside = FakeSearch()
    assert (await _run(FakeQdrant(), outside, tenant="acme"))[0].startswith("q one") and outside.requests == []


async def test_the_named_cohorts_obey_enabled_and_rollback(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_TENANTS", "default")
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_TENANTS", "default")
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_ENABLED", True)
    for name, value in (("OPENSEARCH_ENABLED", False), ("OPENSEARCH_ROLLBACK", True)):
        monkeypatch.setattr(settings, "OPENSEARCH_ENABLED", True)
        monkeypatch.setattr(settings, "OPENSEARCH_ROLLBACK", False)
        monkeypatch.setattr(settings, name, value)
        search = FakeSearch()
        docs = await _run(FakeQdrant(), search, tenant="default")
        assert docs[0].startswith("q one") and search.requests == [], name


async def test_a_named_shadow_tenant_is_shadowed_at_zero_percent(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_TENANTS", "default")
    search = FakeSearch()
    with caplog.at_level(logging.INFO, logger=retriever.logger.name):
        docs = await _run(FakeQdrant(), search, tenant="default")
    assert docs[0].startswith("q one") and len(search.requests) == 1
    line = next(r.getMessage() for r in caplog.records if "Retrieval shadow" in r.getMessage())
    assert "qdrant_ms=" in line and "opensearch_ms=" in line


async def test_a_slow_opensearch_times_out_and_qdrant_answers(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_CANARY_PERCENT", 100)
    monkeypatch.setattr(settings, "OPENSEARCH_RETRIEVAL_TIMEOUT_SECONDS", 0.05)
    docs = await _run(FakeQdrant(), FakeSearch(delay=1.0))
    assert docs == ["q one [Source: q.pdf]", "q two [Source: q.pdf]"]


async def test_a_slow_shadow_cannot_change_the_reply(monkeypatch) -> None:
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_ENABLED", True)
    monkeypatch.setattr(settings, "OPENSEARCH_SHADOW_PERCENT", 100)
    monkeypatch.setattr(settings, "OPENSEARCH_RETRIEVAL_TIMEOUT_SECONDS", 0.05)
    docs = await _run(FakeQdrant(), FakeSearch(delay=1.0))
    assert docs == ["q one [Source: q.pdf]", "q two [Source: q.pdf]"]
