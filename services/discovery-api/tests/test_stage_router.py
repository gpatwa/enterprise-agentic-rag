import time

import pytest
from pydantic import ValidationError

from app.ranking.router import (
    FallbackReason,
    RankingMode,
    RankingStageRouter,
    RouterCandidate,
    StageConfig,
    StageName,
    StageOutput,
    StageRouterRequest,
)


def _request(mode=RankingMode.FULL_RANK):
    return StageRouterRequest(
        request_id="request-1",
        mode=mode,
        candidates=(
            RouterCandidate(candidate_id="item-1", score=0.9, original_rank=1),
            RouterCandidate(candidate_id="item-2", score=0.8, original_rank=2),
        ),
    )


def test_router_applies_ordered_chain_and_versions_are_redacted_contracts():
    seen = []

    def stage(candidates):
        seen.append(tuple(item.candidate_id for item in candidates))
        return StageOutput(candidates=tuple(reversed(candidates)), reason_codes=("quality_signal",))

    router = RankingStageRouter(
        {StageName.HYBRID: stage, StageName.PRE_RANK: stage},
        (StageConfig(stage=StageName.HYBRID, component_version="hybrid-v2"), StageConfig(stage=StageName.PRE_RANK)),
    )
    result = router.route(StageRouterRequest(request_id="request-1", mode=RankingMode.PRE_RANK, candidates=_request().candidates))
    assert seen == [("item-1", "item-2"), ("item-2", "item-1")]
    assert tuple(item.candidate_id for item in result.candidates) == ("item-1", "item-2")
    assert result.trace[0].component_version == "hybrid-v2"
    assert result.trace[0].reason_codes == ("quality_signal",)


def test_missing_and_disabled_stages_fall_back_without_changing_candidates():
    result = RankingStageRouter(
        {StageName.HYBRID: lambda candidates: StageOutput(candidates=tuple(reversed(candidates)))},
        (StageConfig(stage=StageName.HYBRID), StageConfig(stage=StageName.PRE_RANK, enabled=False)),
    ).route(StageRouterRequest(request_id="request-1", mode=RankingMode.PRE_RANK, candidates=_request().candidates))
    assert result.trace[1].fallback_reason is FallbackReason.STAGE_DISABLED
    assert result.fallback is True
    assert all(item.eligible for item in result.candidates)


def test_failed_timed_out_and_invalid_stages_are_closed_world():
    def fail(_):
        raise RuntimeError("private model detail")

    def slow(_):
        time.sleep(0.03)
        return StageOutput(candidates=())

    def add_candidate(_):
        return StageOutput(candidates=(RouterCandidate(candidate_id="item-9"),))

    for handler, reason in ((fail, FallbackReason.STAGE_FAILED), (slow, FallbackReason.STAGE_TIMEOUT), (add_candidate, FallbackReason.STAGE_OUTPUT_INVALID)):
        result = RankingStageRouter(
            {StageName.HYBRID: handler},
            (StageConfig(stage=StageName.HYBRID, timeout_ms=5),),
        ).route(StageRouterRequest(request_id="request-1", mode=RankingMode.HYBRID_ONLY, candidates=_request().candidates))
        assert result.trace[0].fallback_reason is reason
        assert tuple(item.candidate_id for item in result.candidates) == ("item-1", "item-2")


def test_ineligible_candidates_are_removed_and_trace_is_immutable():
    request = StageRouterRequest(
        request_id="request-1",
        mode=RankingMode.HYBRID_ONLY,
        candidates=(_request().candidates[0], RouterCandidate(candidate_id="item-2", eligible=False)),
    )
    result = RankingStageRouter().route(request)
    assert tuple(item.candidate_id for item in result.candidates) == ("item-1",)
    with pytest.raises((ValidationError, TypeError)):
        result.trace = ()
