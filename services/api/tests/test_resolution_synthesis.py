import pytest
from tests.fakes.llm import ScriptedLLM

from app.resolution.evidence import build_evidence_packet
from app.resolution.retrieval import RetrievalProvenance
from app.resolution.synthesis import synthesize_resolution
from app.search.models import RetrievalSource, SearchMode, SearchResult


def packet():
    result = SearchResult(document_id="d1", tenant_id="t1", source_type="kb", source_id="s1",
                          title="Export timeout", text="Retry after refreshing the session.",
                          metadata={}, score=1, rank=1, retrieval_source=RetrievalSource.LEXICAL,
                          index_generation="i1", content_version="c1", permission_version="p1",
                          embedding_model_version="e1")
    provenance = RetrievalProvenance(document_id="d1", query="export", mode=SearchMode.LEXICAL,
                                     score=1, rank=1)
    return build_evidence_packet((result,), (provenance,))


@pytest.mark.asyncio
async def test_synthesizes_strict_json_and_captures_safe_request():
    llm = ScriptedLLM({"claims": [{"text": "Retry is advised", "citation_labels": ["[E1]"]}],
                       "citations": [{"label": "[E1]", "source_id": "s1"}],
                       "steps": [{"instruction": "Retry", "citation_labels": ["[E1]"]}],
                       "customer_response": "Please retry.", "confidence": "medium",
                       "abstention": False, "next_action": "suggest_agent_response"})
    outcome = await synthesize_resolution(llm, " export   timeout ", packet())
    assert outcome.abstention is False
    assert llm.calls[0].json_mode is True
    assert "untrusted quoted data" in llm.calls[0].messages[0]["content"]


@pytest.mark.asyncio
async def test_malformed_or_unknown_citation_abstains():
    llm = ScriptedLLM("not json")
    outcome = await synthesize_resolution(llm, "export timeout", packet())
    assert outcome.abstention is True
    assert outcome.next_action == "route_to_human"
    assert outcome.citations[0].source_id == "s1"
