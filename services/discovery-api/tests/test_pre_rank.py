import pytest
from pydantic import ValidationError

from app.ranking.contracts import FeatureKind, FeatureSet, FeatureValue, RankingContext
from app.ranking.pre_rank import DeterministicPreRanker, PreRankCandidate, PreRankConfig


def _features(subject_id, kind, values, version="pre-rank-v1"):
    return FeatureSet(
        subject_id=subject_id,
        feature_kind=kind,
        feature_version=version,
        features=tuple(FeatureValue(name=name, kind="numeric", numeric_value=value) for name, value in values.items()),
    )


def _context(*items, user_values=None, version="pre-rank-v1"):
    return RankingContext(
        tenant_id="tenant-1",
        request_id="request-1",
        ranking_version=version,
        user=_features("user-1", FeatureKind.USER, user_values) if user_values is not None else None,
        context=_features("request-1", FeatureKind.CONTEXT, {"hour": 1}, version),
        candidates=tuple(_features(item, FeatureKind.ITEM, values, version) for item, values in items),
    )


def _candidate(candidate_id, rank=1, *, source="hybrid", reasons=("retrieved",)):
    return PreRankCandidate(
        candidate_id=candidate_id,
        source=source,
        original_rank=rank,
        base_score=0.4,
        reason_codes=reasons,
        evidence=("source:hybrid",),
    )


def test_pre_rank_scores_allowlisted_features_and_preserves_provenance():
    context = _context(("item-a", {"quality": 0.9}), ("item-b", {"quality": 0.1}), user_values={"plays": 2})
    result = DeterministicPreRanker(PreRankConfig(feature_weights={"quality": 0.5}, limit=1)).rank(
        context, (_candidate("item-b", 2), _candidate("item-a"))
    )
    assert [item.candidate_id for item in result.items] == ["item-a"]
    assert result.items[0].source == "hybrid"
    assert result.items[0].reason_codes == ("retrieved",)
    result.validate_against((_candidate("item-b", 2), _candidate("item-a")), ranking_version="pre-rank-v1")


def test_no_history_fallback_keeps_original_order_and_caps_output():
    context = _context(("item-a", {"quality": 0.1}), ("item-b", {"quality": 0.9}))
    result = DeterministicPreRanker(PreRankConfig(feature_weights={"quality": 1.0}, limit=1)).rank(
        context, (_candidate("item-a"), _candidate("item-b", 2))
    )
    assert result.used_history is False
    assert [item.candidate_id for item in result.items] == ["item-a"]


def test_pre_rank_rejects_unknown_or_outside_candidates_and_ineligible_items():
    context = _context(("item-a", {"quality": 0.5}))
    ranker = DeterministicPreRanker(PreRankConfig(feature_weights={"quality": 1.0}))
    with pytest.raises(ValueError, match="outside"):
        ranker.rank(context, (_candidate("item-missing"),))
    with pytest.raises(ValueError, match="unknown"):
        ranker.rank(_context(("item-a", {"mystery": 0.5}), user_values={"plays": 1}), (_candidate("item-a"),))
    with pytest.raises(ValidationError):
        PreRankCandidate.model_validate({**_candidate("item-a").model_dump(), "eligible": False})


def test_pre_rank_rejects_mixed_versions_nonfinite_weights_and_provenance_mutation():
    with pytest.raises(ValidationError):
        PreRankConfig(feature_weights={"quality": float("nan")})
    context = _context(("item-a", {"quality": 0.5}))
    with pytest.raises(ValueError, match="version"):
        DeterministicPreRanker(PreRankConfig(ranking_version="pre-rank-v2")).rank(context, (_candidate("item-a"),))
    result = DeterministicPreRanker().rank(context, (_candidate("item-a"),))
    mutated = result.items[0].model_copy(update={"source": "other"})
    with pytest.raises(ValueError, match="provenance"):
        result.model_copy(update={"items": (mutated,)}).validate_against((_candidate("item-a"),), ranking_version="pre-rank-v1")
