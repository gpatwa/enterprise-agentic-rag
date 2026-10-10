# services/api/tests/test_support_resolver.py
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError


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


class SlowLLM:
    async def chat_completion(self, messages, temperature=0.7, json_mode=False):
        await asyncio.sleep(1)
        return "This should time out."


class UncitedLLM:
    async def chat_completion(self, messages, temperature=0.7, json_mode=False):
        return "Restart the export worker and retry the CSV export."


class FabricatedCitationLLM:
    async def chat_completion(self, messages, temperature=0.7, json_mode=False):
        return "Restart the export worker and retry the CSV export [9]."


class FakeResolutionPipeline:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    async def resolve(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.result


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
    def test_support_response_requires_typed_grounding_fields(self):
        from app.routes.support import SupportResolveResponse

        response = SupportResolveResponse(
            answer="No matching resolution.",
            confidence="low",
            citations=[],
            matches=[],
            next_action="route_to_human",
            evidence={"verification_status": "unverified", "citation_count": 0},
            abstention=True,
            next_action_data={
                "name": "route_to_human",
                "explanation": "A support agent should review this issue.",
            },
        )

        assert response.evidence.verification_status == "unverified"
        assert response.abstention is True

        with pytest.raises(ValidationError):
            SupportResolveResponse(
                answer="bad",
                confidence="low",
                citations=[],
                matches=[],
                next_action="route_to_human",
                evidence={"verification_status": "verified", "citation_count": -1},
                next_action_data={
                    "name": "route_to_human",
                    "explanation": "review",
                },
            )

    @pytest.fixture(autouse=True)
    def reset_resolution_pipeline(self):
        import app.support.resolver as resolver_mod

        resolver_mod.set_resolution_pipeline(None)
        yield
        resolver_mod.set_resolution_pipeline(None)

    @pytest.mark.asyncio
    async def test_resolution_pipeline_is_disabled_by_default(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        pipeline = FakeResolutionPipeline({"answer": "pipeline [1]", "confidence": "high", "citations": [], "next_action": "agent_review"})
        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([_match()]))
        resolver_mod.set_clients(None)
        resolver_mod.set_resolution_pipeline(pipeline)

        result = await support_resolver.resolve(tenant_id="tenant-a", question="export timeout")

        assert pipeline.calls == []
        assert "Likely related prior resolution" in result["answer"]

    @pytest.mark.asyncio
    async def test_enabled_pipeline_returns_grounded_response_and_scope(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        pipeline = FakeResolutionPipeline({
            "answer": "Restart the export worker [E1].",
            "confidence": "high",
            "citations": [{"label": "[E1]", "source_id": "42"}],
            "next_action": "suggest_agent_response",
            "abstention": False,
            "prompt": "must not be returned",
        })
        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([_match(), _match(0.83)]))
        resolver_mod.set_clients(None)
        resolver_mod.set_resolution_pipeline(pipeline, enabled=True)
        scope = {"tenant_id": "tenant-a", "principal": "agent-1", "acl": ["support"]}

        result = await support_resolver.resolve(tenant_id="tenant-a", question="export timeout", acl_scope=scope)

        assert result["answer"] == "Restart the export worker [E1]."
        assert result["matches"]
        assert "prompt" not in result
        assert pipeline.calls[0]["tenant_id"] == "tenant-a"
        assert pipeline.calls[0]["acl_scope"] is scope

    @pytest.mark.asyncio
    async def test_enabled_pipeline_failure_uses_deterministic_fallback(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        pipeline = FakeResolutionPipeline(error=TimeoutError("provider timeout"))
        llm = FakeLLM()
        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([_match()]))
        resolver_mod.set_clients(llm)
        resolver_mod.set_resolution_pipeline(pipeline, enabled=True)

        result = await support_resolver.resolve(tenant_id="tenant-a", question="export timeout")

        assert "Likely related prior resolution" in result["answer"]
        assert llm.messages == []

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

    @pytest.mark.asyncio
    async def test_resolve_falls_back_when_llm_times_out(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.config import settings
        from app.support.resolver import support_resolver

        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([_match()]))
        monkeypatch.setattr(settings, "SUPPORT_RESOLVE_LLM_TIMEOUT_SECONDS", 0.01)
        resolver_mod.set_clients(SlowLLM())

        try:
            result = await support_resolver.resolve(
                tenant_id="tenant-a",
                question="exports time out after 30 seconds",
                limit=5,
            )

            assert "Likely related prior resolution" in result["answer"]
            assert result["citations"][0]["source_id"] == "42"
        finally:
            resolver_mod.set_clients(None)

    @pytest.mark.asyncio
    async def test_resolve_falls_back_when_llm_omits_citations(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([_match()]))
        resolver_mod.set_clients(UncitedLLM())

        try:
            result = await support_resolver.resolve(
                tenant_id="tenant-a",
                question="exports time out after 30 seconds",
                limit=5,
            )

            assert "Likely related prior resolution" in result["answer"]
            assert "[1]" in result["answer"]
            assert "retry the CSV export." not in result["answer"]
        finally:
            resolver_mod.set_clients(None)

    @pytest.mark.asyncio
    async def test_resolve_falls_back_when_llm_fabricates_citations(self, monkeypatch):
        import app.support.resolver as resolver_mod
        from app.support.resolver import support_resolver

        monkeypatch.setattr(resolver_mod, "support_indexer", FakeSupportIndexer([_match()]))
        resolver_mod.set_clients(FabricatedCitationLLM())

        try:
            result = await support_resolver.resolve(
                tenant_id="tenant-a",
                question="exports time out after 30 seconds",
                limit=5,
            )

            assert "Likely related prior resolution" in result["answer"]
            assert "[1]" in result["answer"]
            assert "[9]" not in result["answer"]
        finally:
            resolver_mod.set_clients(None)
