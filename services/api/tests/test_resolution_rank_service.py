import asyncio

from tests.fakes.llm import ScriptedLLM

from app.resolution.rank_service import RankingPolicy, RankingStage, rank_authorized
from app.resolution.ranking import RerankCandidate, RerankRequest


def request():
    return RerankRequest(
        query_id="q", query="reset", scope_identity="t/p",
        candidates=(
            RerankCandidate(document_id="b", original_rank=1, original_score=.8, source_type="a", source_id="b", index_version="i", permission_version="p", evidence_version="e"),
            RerankCandidate(document_id="a", original_rank=2, original_score=.2, source_type="a", source_id="a", index_version="i", permission_version="p", evidence_version="e"),
        ),
    )


def run(**kwargs):
    return asyncio.run(rank_authorized(request(), **kwargs))


def test_baseline_preserves_original_order():
    assert [i.document_id for i in run().items] == ["b", "a"]


def test_feature_stage_and_tie_breaking():
    result = run(policy=RankingPolicy(stage=RankingStage.FEATURE), features_by_document={})
    assert [i.document_id for i in result.items] == ["b", "a"]
    tied = request().model_copy(update={"candidates": tuple(c.model_copy(update={"original_score": .5}) for c in request().candidates)})
    result = asyncio.run(rank_authorized(tied, policy=RankingPolicy(stage=RankingStage.FEATURE)))
    assert [i.document_id for i in result.items] == ["a", "b"]


def test_llm_stage_uses_scripted_scores_and_preserves_provenance():
    client = ScriptedLLM({"scores": {"a": .9, "b": .1}, "reasons": {"a": ["exact"], "b": []}})
    result = run(policy=RankingPolicy(stage=RankingStage.LLM), client=client)
    assert [i.document_id for i in result.items] == ["a", "b"]
    assert result.validate_against(request()) == result


def test_kill_switch_and_llm_failures_fall_back_without_calling_or_raising():
    client = ScriptedLLM(RuntimeError("down"))
    result = run(policy=RankingPolicy(stage=RankingStage.LLM, kill_switch=True), client=client)
    assert [i.document_id for i in result.items] == ["b", "a"] and not client.calls
    result = run(policy=RankingPolicy(stage=RankingStage.LLM), client=client)
    assert [i.document_id for i in result.items] == ["b", "a"]
