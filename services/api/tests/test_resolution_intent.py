import pytest
from tests.fakes.llm import ScriptedLLM

from app.resolution.intent import extract_support_intent
from app.resolution.models import ConfidenceLevel, SupportIntentType


@pytest.mark.asyncio
async def test_extracts_strict_support_intent_and_separates_ticket_data():
    client = ScriptedLLM({"intent": "incident", "entities": [], "constraints": [], "exact_terms": ["ERR-7"], "reason": "error", "confidence": "high"})
    result = await extract_support_intent(client, "Exports fail intermittently after deploy")
    assert result.intent is SupportIntentType.INCIDENT
    assert client.calls[0].json_mode is True
    assert client.calls[0].messages[0]["role"] == "system"
    assert client.calls[0].messages[1]["role"] == "user"
    assert "<ticket>" in client.calls[0].messages[1]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ["not json", {"intent": "bogus"}, {"intent": "unknown", "reason": "", "confidence": "low"}])
async def test_malformed_or_invalid_output_uses_deterministic_fallback(response):
    result = await extract_support_intent(ScriptedLLM(response), "Exports fail intermittently")
    assert result.intent is SupportIntentType.UNKNOWN
    assert result.confidence is ConfidenceLevel.LOW


@pytest.mark.asyncio
async def test_timeout_and_obvious_fast_path_do_not_depend_on_model_output():
    result = await extract_support_intent(ScriptedLLM().enqueue_timeout(1), "HTTP 503 from export API", timeout_seconds=0.01)
    assert result.intent is SupportIntentType.INCIDENT
    client = ScriptedLLM({"intent": "billing", "reason": "wrong", "confidence": "high"})
    result = await extract_support_intent(client, "I cannot access the admin console")
    assert result.intent is SupportIntentType.ACCESS
    assert not client.calls
