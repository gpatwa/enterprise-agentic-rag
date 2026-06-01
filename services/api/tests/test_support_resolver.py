# services/api/tests/test_support_resolver.py
from __future__ import annotations

import os

import pytest

os.environ.setdefault("DATA_ANALYTICS_ENABLED", "false")


class FakeSupportIndexer:
    def __init__(self, results):
        self.results = results
        self.calls = []

    async def search(self, **kwargs):
        self.calls.append(kwargs)
        return self.results


class FakeLLM:
    def __init__(self):
        self.messages = []

    async def chat_completion(self, messages, temperature=0.7, json_mode=False):
        self.messages.append(
            {"messages": messages, "temperature": temperature, "json_mode": json_mode}
        )
        return "Likely cause is an export worker timeout. Restart the worker and retry [1]."


def _match(score=0.91):
    return {
        "id": "point-1",
        "score": score,
        "provider": "zendesk",
        "source_type": "ticket",
        "source_id": "42",
        "title": "API timeout on export",
        "text": "Restarting the export worker resolved the timeout.",
        "status": "solved",
        "priority": "high",
        "tags": ["api", "export"],
        "source_url": "https://example.zendesk.com/tickets/42",
        "chunk_index": 0,
        "chunk_count": 1,
    }


class TestSupportResolver:
    @pytest.mark.asyncio
    async def test_resolve_generates_cited_answer_from_support_index(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        fake_indexer = FakeSupportIndexer([_match(), _match(score=0.83)])
        fake_llm = FakeLLM()
        monkeypatch.setattr(resolver_mod, "support_indexer", fake_indexer)
        resolver_mod.set_clients(fake_llm)

        try:
            result = await support_resolver.resolve(
                tenant_id="tenant-a",
                question="exports time out after 30 seconds",
                provider="zendesk",
                limit=5,
            )

            assert result["confidence"] == "high"
            assert result["next_action"] == "suggest_agent_response"
            assert result["citations"][0]["label"] == "[1]"
            assert result["citations"][0]["source_id"] == "42"
            assert "Restart the worker" in result["answer"]
            assert fake_indexer.calls[0]["tenant_id"] == "tenant-a"
            assert fake_indexer.calls[0]["provider"] == "zendesk"
            assert fake_llm.messages[0]["temperature"] == 0.2
        finally:
            resolver_mod.set_clients(None)

    @pytest.mark.asyncio
    async def test_resolve_returns_low_confidence_when_no_matches(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([]))
        resolver_mod.set_clients(FakeLLM())

        try:
            result = await support_resolver.resolve(
                tenant_id="tenant-a",
                question="unknown issue",
                limit=5,
            )

            assert result["confidence"] == "low"
            assert result["citations"] == []
            assert result["matches"] == []
            assert result["next_action"] == "route_to_human"
        finally:
            resolver_mod.set_clients(None)
