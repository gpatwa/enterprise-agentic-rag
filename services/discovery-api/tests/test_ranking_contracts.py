import pytest
from pydantic import ValidationError

from app.ranking.contracts import (
    FeatureKind,
    FeatureSet,
    FeatureValue,
    MissingReason,
    Prediction,
    PredictionBatch,
    RankingContext,
)


def _feature(subject_id, kind, name, version="rank-v1"):
    return FeatureSet(
        subject_id=subject_id,
        feature_kind=kind,
        feature_version=version,
        features=(FeatureValue(name=name, kind="numeric", numeric_value=1.0),),
    )


def _context(**overrides):
    values = {
        "tenant_id": "tenant-orbit",
        "request_id": "request-1",
        "ranking_version": "rank-v1",
        "user": _feature("user-1", FeatureKind.USER, "plays"),
        "context": _feature("request-1", FeatureKind.CONTEXT, "hour"),
        "candidates": (
            _feature("item-1", FeatureKind.ITEM, "quality"),
            _feature("item-2", FeatureKind.ITEM, "quality"),
        ),
    }
    values.update(overrides)
    return RankingContext(**values)


def test_contracts_are_immutable_and_typed():
    feature = FeatureValue(name="plays", kind="numeric", numeric_value=2.0)
    assert feature.numeric_value == 2.0
    with pytest.raises((ValidationError, TypeError)):
        feature.numeric_value = 3.0
    with pytest.raises(ValidationError):
        FeatureValue(name="plays", kind="numeric", numeric_value=1.0, boolean_value=True)


def test_missingness_is_explicit_and_values_are_redacted_by_absence():
    missing = FeatureValue(name="social", kind="numeric", missing_reason=MissingReason.CONSENT_DENIED)
    assert missing.numeric_value is None
    assert missing.missing_reason is MissingReason.CONSENT_DENIED
    with pytest.raises(ValidationError):
        FeatureValue(name="social", kind="numeric", numeric_value=1.0, missing_reason=MissingReason.STALE)


def test_ranking_context_rejects_mixed_versions_and_bad_kinds():
    with pytest.raises(ValidationError, match="one feature version"):
        _context(candidates=(_feature("item-1", FeatureKind.ITEM, "quality", "rank-v2"),))
    with pytest.raises(ValidationError, match="context feature set"):
        _context(context=_feature("request-1", FeatureKind.ITEM, "hour"))


def test_context_rejects_duplicate_or_unbounded_features():
    with pytest.raises(ValidationError, match="unique"):
        _context(candidates=(_feature("item-1", FeatureKind.ITEM, "quality"), _feature("item-1", FeatureKind.ITEM, "quality")))
    with pytest.raises(ValidationError):
        FeatureSet(
            subject_id="item-1",
            feature_kind=FeatureKind.ITEM,
            feature_version="rank-v1",
            features=tuple(FeatureValue(name=f"f{i}", kind="numeric", numeric_value=1.0) for i in range(129)),
        )


def test_prediction_batch_is_scoped_to_supplied_candidates():
    prediction = Prediction(candidate_id="item-1", stage="final", model_version="model-v1", score=0.8)
    batch = PredictionBatch(
        ranking_version="rank-v1",
        model_version="model-v1",
        candidate_ids=("item-1", "item-2"),
        predictions=(prediction,),
    )
    assert batch.predictions[0].candidate_id == "item-1"
    with pytest.raises(ValidationError, match="outside supplied batch"):
        PredictionBatch(
            ranking_version="rank-v1",
            model_version="model-v1",
            candidate_ids=("item-1",),
            predictions=(Prediction(candidate_id="item-9", stage="final", model_version="model-v1", score=0.2),),
        )


def test_predictions_reject_nonfinite_scores_unknown_fields_and_model_mismatch():
    with pytest.raises(ValidationError):
        Prediction(candidate_id="item-1", stage="final", model_version="model-v1", score=float("nan"))
    with pytest.raises(ValidationError):
        Prediction.model_validate({"candidate_id": "item-1", "stage": "final", "model_version": "model-v1", "score": 1.0, "policy": "approved"})
    with pytest.raises(ValidationError, match="model versions"):
        PredictionBatch(
            ranking_version="rank-v1",
            model_version="model-v1",
            candidate_ids=("item-1",),
            predictions=(Prediction(candidate_id="item-1", stage="final", model_version="model-v2", score=0.2),),
        )
