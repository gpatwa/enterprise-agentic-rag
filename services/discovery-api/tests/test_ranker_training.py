from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState
from app.events.models import EventType, ImpressionPayload, InteractionEvent
from app.features.materialization import FeatureKind, FeatureRecord
from app.training.examples import CandidatePool, TimeSplitBoundaries, TrainingExampleBuilder
from app.training.ranker import RankerTrainingConfig, train_offline_ranker
from packages.platform_contracts.discovery import DiscoveryComponentVersion, DiscoveryRequestContext, ImpressionToken

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _dataset():
    context = DiscoveryRequestContext(tenant_id="tenant-1", principal_id="user-1", request_id="req-1", purpose="recommendation", locale="en-US", device="web")
    token = ImpressionToken.for_context(context, token_id="token-1", issued_at=BASE, expires_at=BASE + timedelta(hours=1), schema_version="v1", components=(DiscoveryComponentVersion(component_type="schema", name="discovery", version="v1", digest="a" * 64),))
    impressions = tuple(
        InteractionEvent(event_id=f"imp-{index}", event_type=EventType.IMPRESSION, tenant_id="tenant-1", user_id="user-1", experience_id=f"item-{index}", request_id="req-1", occurred_at=BASE + timedelta(days=index), synthetic=True, consent_state=ConsentState.PERSONALIZATION_ALLOWED, impression_token=token, payload=ImpressionPayload(position=0, surface="recommendation", source="seed", result_set_id=f"set-{index}"))
        for index in range(3)
    )
    features = tuple(
        FeatureRecord(tenant_id="tenant-1", subject_type=kind, subject_id=subject, feature_version="features-v1", as_of=BASE, source_watermark=BASE, feature_age_seconds=0.0, consent_state=ConsentState.PERSONALIZATION_ALLOWED, synthetic=True, values={"quality": float(index)})
        for index, (kind, subject) in enumerate(((FeatureKind.USER, "user-1"), (FeatureKind.CONTEXT, "user-1"), (FeatureKind.ITEM, "item-0"), (FeatureKind.ITEM, "item-1"), (FeatureKind.ITEM, "item-2")))
    )
    pools = tuple(CandidatePool(tenant_id="tenant-1", user_id="user-1", request_id="req-1", as_of=BASE, candidate_ids=(f"item-{index}",)) for index in range(3))
    # Each request must have a distinct request lineage for the builder; use the first request only.
    impression = impressions[0]
    return TrainingExampleBuilder().build((impression,), features, candidate_pools=(pools[0],), splits=TimeSplitBoundaries(validation_at=BASE + timedelta(days=1), test_at=BASE + timedelta(days=2)))


def test_training_is_repeatable_and_manifest_is_redacted():
    dataset = _dataset()
    config = RankerTrainingConfig(use_lightgbm=False, seed=11)
    first = train_offline_ranker(dataset, config)
    second = train_offline_ranker(dataset, config)
    assert first.manifest.model_dump() == second.manifest.model_dump()
    assert first.manifest.fallback is True
    assert "quality" not in first.manifest.model_dump_json()
    assert first.manifest.artifact_checksum


def test_versions_and_bounds_are_validated():
    dataset = _dataset()
    with pytest.raises(ValueError, match="dataset version"):
        train_offline_ranker(dataset, RankerTrainingConfig(dataset_version="other", use_lightgbm=False))
    with pytest.raises(ValueError, match="max_rows"):
        train_offline_ranker(dataset, RankerTrainingConfig(max_rows=0, use_lightgbm=False))
