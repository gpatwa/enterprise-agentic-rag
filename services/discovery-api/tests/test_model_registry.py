from datetime import datetime, timezone

import pytest

from app.ranking.registry import ModelCompatibility, ModelEvidence, ModelRecord, ModelRegistry, ModelState, checksum_for


def _compatibility() -> ModelCompatibility:
    return ModelCompatibility(
        dataset_version="dataset.v1",
        feature_version="features.v1",
        policy_version="policy.v1",
        ranking_version="ranking.v1",
        artifact_checksum="a" * 64,
        training_manifest_checksum="b" * 64,
    )


def _evidence() -> ModelEvidence:
    return ModelEvidence(evaluation_checksum="c" * 64, evidence_ids=("eval.v1", "review.v1"), approved_by="reviewer-1")


def _record(version: str = "model.v1") -> ModelRecord:
    return ModelRecord(
        model_name="home-ranker",
        model_version=version,
        compatibility=_compatibility(),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        metadata_checksum=checksum_for((version, "home-ranker")),
    )


def test_registry_requires_evidence_and_tracks_immutable_transitions() -> None:
    registry = ModelRegistry(expected=_compatibility())
    draft = registry.register(_record())
    assert draft.state is ModelState.DRAFT
    with pytest.raises(ValueError, match="requires evidence"):
        registry.promote("home-ranker", "model.v1", ModelState.CANDIDATE)
    candidate = registry.promote("home-ranker", "model.v1", ModelState.CANDIDATE, evidence=_evidence())
    approved = registry.promote("home-ranker", "model.v1", ModelState.APPROVED, evidence=_evidence())
    assert candidate.state is ModelState.CANDIDATE
    assert approved.state is ModelState.APPROVED
    assert draft.state is ModelState.DRAFT
    assert registry.active("home-ranker").model_version == "model.v1"
    assert len(registry.audits) == 3


def test_registry_rejects_duplicates_incompatible_models_and_bad_transitions() -> None:
    registry = ModelRegistry(expected=_compatibility())
    registry.register(_record())
    with pytest.raises(ValueError, match="already exists"):
        registry.register(_record())
    incompatible = _record("model.v2").model_copy(update={"compatibility": _compatibility().model_copy(update={"feature_version": "features.v2"})})
    with pytest.raises(ValueError, match="compatibility"):
        registry.register(incompatible)
    with pytest.raises(ValueError, match="invalid transition"):
        registry.promote("home-ranker", "model.v1", ModelState.APPROVED, evidence=_evidence())


def test_rollback_restores_deprecated_version_and_keeps_audit_append_only() -> None:
    registry = ModelRegistry(expected=_compatibility())
    first = registry.register(_record("model.v1"))
    registry.promote(first.model_name, first.model_version, ModelState.CANDIDATE, evidence=_evidence())
    registry.promote(first.model_name, first.model_version, ModelState.APPROVED, evidence=_evidence())
    second = registry.register(_record("model.v2"))
    registry.promote(second.model_name, second.model_version, ModelState.CANDIDATE, evidence=_evidence())
    registry.promote(second.model_name, second.model_version, ModelState.APPROVED, evidence=_evidence())
    registry.deprecate("home-ranker", "model.v1")
    restored = registry.rollback("home-ranker", "model.v1")
    assert restored.state is ModelState.APPROVED
    assert registry.active("home-ranker").model_version == "model.v1"
    assert len(registry.audits) == 9
    assert all("artifact" not in audit.model_dump_json() for audit in registry.audits)
