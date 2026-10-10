from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState
from app.events.models import ClickPayload, EventType, ImpressionPayload, InteractionEvent
from app.features.materialization import FeatureKind, FeatureRecord
from app.training.examples import (
    CandidatePool,
    ExposureState,
    LabelKind,
    TimeSplit,
    TimeSplitBoundaries,
    TrainingExampleBuilder,
)
from packages.platform_contracts.discovery import DiscoveryComponentVersion, DiscoveryRequestContext, ImpressionToken

UTC = timezone.utc
BASE = datetime(2026, 1, 1, tzinfo=UTC)


def _token(request_id="req-1"):
    context = DiscoveryRequestContext(tenant_id="tenant-1", principal_id="user-1", request_id=request_id, purpose="recommendation", locale="en-US", device="web")
    return ImpressionToken.for_context(context, token_id=f"token-{request_id}", issued_at=BASE, expires_at=BASE + timedelta(hours=1), schema_version="v1", components=(DiscoveryComponentVersion(component_type="schema", name="discovery", version="v1", digest="a" * 64),))


def _event(event_id, event_type, experience_id, at, token, payload):
    return InteractionEvent(event_id=event_id, event_type=event_type, tenant_id="tenant-1", user_id="user-1", experience_id=experience_id, request_id="req-1", occurred_at=at, synthetic=True, consent_state=ConsentState.PERSONALIZATION_ALLOWED, impression_token=token, payload=payload)


def _features(as_of=BASE):
    values = []
    for kind, subject in ((FeatureKind.USER, "user-1"), (FeatureKind.CONTEXT, "user-1"), (FeatureKind.ITEM, "item-1"), (FeatureKind.ITEM, "item-2")):
        values.append(FeatureRecord(tenant_id="tenant-1", subject_type=kind, subject_id=subject, feature_version="features-v1", as_of=as_of, source_watermark=as_of, feature_age_seconds=0.0, consent_state=ConsentState.PERSONALIZATION_ALLOWED, synthetic=True, values={"quality": 1.0}))
    return tuple(values)


def _build(**kwargs):
    token = _token()
    impression = _event("imp-1", EventType.IMPRESSION, "item-1", BASE, token, ImpressionPayload(position=0, surface="recommendation", source="seed", result_set_id="set-1"))
    click = _event("click-1", EventType.CLICK, "item-1", BASE + timedelta(minutes=1), token, ClickPayload())
    pool = CandidatePool(tenant_id="tenant-1", user_id="user-1", request_id="req-1", as_of=BASE, candidate_ids=("item-1", "item-2"))
    values = {"impressions": (impression,), "features": _features(), "events": (click,), "candidate_pools": (pool,), "splits": TimeSplitBoundaries(validation_at=BASE + timedelta(days=1), test_at=BASE + timedelta(days=2))}
    values.update(kwargs)
    return TrainingExampleBuilder(cohort="short-history").build(**values)


def test_examples_distinguish_exposed_click_from_unexposed_and_split_deterministically():
    dataset = _build()
    assert dataset.examples_checksum == _build().examples_checksum
    exposed = next(item for item in dataset.examples if item.exposure is ExposureState.EXPOSED)
    unexposed = next(item for item in dataset.examples if item.exposure is ExposureState.UNEXPOSED)
    assert (exposed.label, exposed.label_value, exposed.split) == (LabelKind.CLICK, 1.0, TimeSplit.TRAIN)
    assert (unexposed.label, unexposed.label_value) == (LabelKind.UNEXPOSED, 0.0)
    assert dataset.manifest["unexposed_count"] == 1


def test_future_events_and_features_do_not_join():
    token = _token()
    future = _event("future", EventType.CLICK, "item-1", BASE + timedelta(days=3), token, ClickPayload())
    with pytest.raises(ValueError, match="no point-in-time"):
        _build(features=_features(as_of=BASE + timedelta(hours=1)), events=(future,))


def test_rejects_cross_tenant_duplicate_and_unbounded_inputs():
    pool = CandidatePool(tenant_id="tenant-1", user_id="user-1", request_id="req-1", as_of=BASE, candidate_ids=("item-1",))
    with pytest.raises(ValueError, match="candidate pool"):
        _build(candidate_pools=(pool.model_copy(update={"user_id": "user-2"}),))
    with pytest.raises(ValueError, match="unique"):
        _build(candidate_pools=(pool, pool))
    with pytest.raises(ValueError, match="max_examples"):
        TrainingExampleBuilder(max_examples=0)


def test_rejects_future_snapshot_and_mixed_feature_versions():
    with pytest.raises(ValueError, match="feature snapshots"):
        _build(features=_features()[:-1] + (_features()[3].model_copy(update={"feature_version": "other"}),))
