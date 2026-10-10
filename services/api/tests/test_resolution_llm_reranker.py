import asyncio

from tests.fakes.llm import ScriptedLLM

from app.resolution.llm_reranker import MAX_REASON_CODE_LENGTH, MAX_REASON_CODES, MAX_RESPONSE_LENGTH, rerank_with_llm
from app.resolution.ranking import RerankCandidate, RerankRequest


def make_request():
    return RerankRequest(query_id="q", query="reset password", scope_identity="tenant/t/principal/p", candidates=(
        RerankCandidate(document_id="a", original_rank=1, original_score=.4, source_type="article", source_id="a", index_version="i", permission_version="p", evidence_version="e", evidence_metadata={"title": "Reset", "text": "Use the portal."}),
        RerankCandidate(document_id="b", original_rank=2, original_score=.3, source_type="article", source_id="b", index_version="i", permission_version="p", evidence_version="e"),
    ))


def test_valid_one_call_reranks_and_preserves_input_order_and_provenance():
    client = ScriptedLLM({"scores": {"a": .2, "b": .9}, "reasons": {"a": ["weak"], "b": ["exact"]}})
    result = asyncio.run(rerank_with_llm(client, make_request()))
    assert [i.document_id for i in result.items] == ["a", "b"]
    assert result.items[1].score == .9
    assert len(client.calls) == 1 and client.calls[0].json_mode
    assert "Reset" in client.calls[0].messages[1]["content"]


def test_unknown_missing_duplicate_invalid_or_malformed_output_falls_back():
    for output in ({"scores": {"a": .2, "x": .9}, "reasons": {"a": [], "x": []}}, {"scores": {"a": .2}, "reasons": {"a": []}}, {"scores": {"a": 2, "b": .1}, "reasons": {"a": [], "b": []}}, "not json"):
        result = asyncio.run(rerank_with_llm(ScriptedLLM(output), make_request()))
        assert [i.document_id for i in result.items] == ["a", "b"]
        assert [i.score for i in result.items] == [.4, .3]


def test_timeout_falls_back():
    client = ScriptedLLM()
    client.enqueue_timeout(.05)
    result = asyncio.run(rerank_with_llm(client, make_request(), timeout_seconds=.001))
    assert [i.score for i in result.items] == [.4, .3]


def test_oversized_response_falls_back_before_json_parsing():
    client = ScriptedLLM("{" + ("x" * MAX_RESPONSE_LENGTH) + "}")
    result = asyncio.run(rerank_with_llm(client, make_request()))
    assert [i.score for i in result.items] == [.4, .3]


def test_oversized_or_too_many_reason_codes_falls_back():
    for reasons in (
        {"a": ["x" * (MAX_REASON_CODE_LENGTH + 1)], "b": []},
        {"a": [str(i) for i in range(MAX_REASON_CODES + 1)], "b": []},
    ):
        output = {"scores": {"a": .2, "b": .9}, "reasons": reasons}
        result = asyncio.run(rerank_with_llm(ScriptedLLM(output), make_request()))
        assert [i.score for i in result.items] == [.4, .3]
