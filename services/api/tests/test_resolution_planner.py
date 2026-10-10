import pytest
from tests.fakes.llm import ScriptedLLM

from app.resolution.models import SupportIntent
from app.resolution.planner import plan_queries
from app.search.models import SearchScope


def scope():
    return SearchScope(tenant_id="acme", principal_id="agent", purpose="support", acl_tokens=("tenant:acme",))


def intent():
    return SupportIntent(intent="incident", exact_terms=["ERR-42"], reason="export failure", confidence="high")


@pytest.mark.asyncio
async def test_plans_bounded_variants_and_preserves_scope_and_terms():
    client = ScriptedLLM({"variants": [
        {"query": "ERR-42 export timeout", "mode": "lexical", "reason": "error and symptom", "confidence": "high"},
        {"query": "ERR-42 export failure", "mode": "semantic", "reason": "related issue", "confidence": "medium"},
    ]})
    result = await plan_queries(client, intent(), scope())
    assert result.scope.tenant_id == "acme"
    assert all("ERR-42" in variant.query for variant in result.variants)
    assert client.calls[0].json_mode is True
    assert "scope" not in client.calls[0].messages[1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["bad", {"variants": []}, {"variants": [{"query": "other", "mode": "lexical", "reason": "x", "confidence": "low"}]}, {"variants": [{"query": "ERR-42", "mode": "bogus", "reason": "x", "confidence": "low"}]}])
async def test_invalid_output_falls_back(response):
    result = await plan_queries(ScriptedLLM(response), intent(), scope())
    assert len(result.variants) <= 4
    assert result.variants[0].query == "ERR-42"
    assert result.variants[0].mode.value == "exact"
    assert result.scope is not None


@pytest.mark.asyncio
async def test_timeout_and_overlong_model_output_fall_back():
    result = await plan_queries(ScriptedLLM().enqueue_timeout(1), intent(), scope(), timeout_seconds=0.01)
    assert result.variants[0].query == "ERR-42"
    result = await plan_queries(ScriptedLLM("x" * 12001), intent(), scope())
    assert result.variants[0].query == "ERR-42"
