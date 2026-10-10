from datetime import datetime, timezone

import pytest

from app.ranking.contracts import FeatureKind, FeatureSet, FeatureValue, RankingContext
from app.ranking.inference import BoundedRankerInference, RankerInferenceRequest
from app.ranking.pre_rank import PreRankCandidate
from app.ranking.registry import ModelCompatibility, ModelEvidence, ModelRecord, ModelRegistry, ModelState, checksum_for


def _compatibility() -> ModelCompatibility:
    return ModelCompatibility(
        dataset_version="dataset.v1", feature_version="features.v1", policy_version="policy.v1",
        ranking_version="ranking.v1", artifact_checksum="a" * 64, training_manifest_checksum="b" * 64,
    )


def _registry() -> ModelRegistry:
    registry = ModelRegistry(expected=_compatibility())
    record = ModelRecord(
        model_name="home-ranker", model_version="model.v1", compatibility=_compatibility(),
        evidence=ModelEvidence(evaluation_checksum="c" * 64, evidence_ids=("eval.v1",), approved_by="reviewer"),
        state=ModelState.DRAFT, created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata_checksum=checksum_for(("home-ranker", "model.v1")),
    )
    registry.register(record)
    registry.promote("home-ranker", "model.v1", ModelState.CANDIDATE, evidence=record.evidence)
    registry.promote("home-ranker", "model.v1", ModelState.APPROVED, evidence=record.evidence)
    return registry


def _request(*, model_version="model.v1", policy_version="policy.v1") -> RankerInferenceRequest:
    feature = FeatureSet(subject_id="item-a", feature_kind=FeatureKind.ITEM, feature_version="features.v1", features=(FeatureValue(name="quality", kind="numeric", numeric_value=1.0),))
    context = RankingContext(
        tenant_id="tenant-1", request_id="request-1", ranking_version="ranking.v1",
        context=FeatureSet(subject_id="request-1", feature_kind=FeatureKind.CONTEXT, feature_version="features.v1", features=(FeatureValue(name="hour", kind="numeric", numeric_value=1.0),)),
        candidates=(feature,),
    )
    return RankerInferenceRequest(
        candidate_batch_id="batch-1", model_name="home-ranker", model_version=model_version,
        feature_version="features.v1", policy_version=policy_version, ranking_version="ranking.v1",
        context=context, candidates=(PreRankCandidate(candidate_id="item-a", source="hybrid", original_rank=1, base_score=0.2),),
    )


class GoodModel:
    def predict(self, context, candidates):
        return {candidate.candidate_id: 0.9 for candidate in candidates}


class BrokenModel:
    def predict(self, context, candidates):
        raise RuntimeError("private model details")


def test_approved_model_scores_only_supplied_candidates_and_preserves_evidence():
    result = BoundedRankerInference(_registry(), {("home-ranker", "model.v1"): GoodModel()}).rank(_request())
    assert result.fallback is False
    assert result.items[0].score == 0.9
    assert result.items[0].candidate_id == "item-a"
    assert result.items[0].eligible is True


def test_unknown_or_incompatible_model_uses_closed_world_fallback():
    result = BoundedRankerInference(_registry(), {}).rank(_request(model_version="model.v9"))
    assert result.fallback is True
    assert result.fallback_reason == "model_incompatible"
    assert [item.candidate_id for item in result.items] == ["item-a"]
    assert "private" not in result.model_dump_json()


def test_model_failure_is_redacted_and_does_not_change_candidates():
    result = BoundedRankerInference(_registry(), {("home-ranker", "model.v1"): BrokenModel()}).rank(_request())
    assert result.fallback_reason == "model_failure"
    assert len(result.items) == 1
    assert result.items[0].reason_codes[-1] == "ranker_fallback"


def test_policy_mismatch_and_invalid_scores_fall_back():
    result = BoundedRankerInference(_registry(), {("home-ranker", "model.v1"): GoodModel()}).rank(_request(policy_version="policy.v2"))
    assert result.fallback_reason == "policy_incompatible"

    class BadModel:
        def predict(self, context, candidates):
            return {candidate.candidate_id: 2.0 for candidate in candidates}

    result = BoundedRankerInference(_registry(), {("home-ranker", "model.v1"): BadModel()}).rank(_request())
    assert result.fallback_reason == "score_range_invalid"


def test_request_rejects_ineligible_candidates_and_unbounded_attempts():
    with pytest.raises(ValueError, match="eligible"):
        RankerInferenceRequest(**{**_request().model_dump(), "candidates": ({**_request().candidates[0].model_dump(), "eligible": False},)})
    with pytest.raises(ValueError, match="attempts"):
        BoundedRankerInference(_registry(), {}, max_attempts=4)
