from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState, ImmersiveDiscoveryContext
from app.features.materialization import FeatureKind, FeatureMaterializer, FeatureTombstone
from app.generation.catalog import generate_catalog
from app.simulation.behavior import BehaviorSimulator
from packages.platform_contracts.discovery import DiscoveryRequestContext

AS_OF = datetime(2026, 1, 1, 0, 1, tzinfo=timezone.utc)


def _run():
    dataset = generate_catalog(7)
    user = dataset.users[1]
    context = ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id=user.tenant_id, principal_id=user.user_id, request_id="req-features", locale=user.locale.value, device="web", purpose="recommendation"
        ),
        surface="recommendation",
    )
    simulation = BehaviorSimulator(3, started_at=datetime(2026, 1, 1, tzinfo=timezone.utc)).simulate(user, dataset.experiences, context)
    return dataset, simulation


def test_materialization_is_deterministic_and_point_in_time():
    dataset, simulation = _run()
    materializer = FeatureMaterializer()
    first = materializer.materialize(dataset.users, dataset.experiences, simulation.events, as_of=AS_OF)
    second = materializer.materialize(dataset.users, dataset.experiences, simulation.events, as_of=AS_OF)

    assert first.records_checksum == second.records_checksum
    assert first.records == second.records
    assert all(record.as_of == AS_OF for record in first.records)
    assert all(record.subject_type in set(FeatureKind) for record in first.records)
    assert all(record.feature_age_seconds >= 0 for record in first.records)


def test_future_events_do_not_change_snapshot():
    dataset, simulation = _run()
    materializer = FeatureMaterializer()
    before = materializer.materialize(dataset.users, dataset.experiences, simulation.events, as_of=AS_OF)
    future_events = tuple(simulation.events) + tuple(
        event.model_copy(update={"event_id": f"future-{event.event_id}", "occurred_at": AS_OF + timedelta(days=2)})
        for event in simulation.events[:1]
    )
    after = materializer.materialize(dataset.users, dataset.experiences, future_events, as_of=AS_OF)

    before_user = next(item for item in before.records if item.subject_type is FeatureKind.USER)
    after_user = next(item for item in after.records if item.subject_type is FeatureKind.USER)
    assert before_user.values == after_user.values


def test_tombstones_remove_subjects_and_manifest_records_deletion():
    dataset, simulation = _run()
    user = dataset.users[1]
    result = FeatureMaterializer().materialize(
        dataset.users,
        dataset.experiences,
        simulation.events,
        as_of=AS_OF,
        tombstones=[FeatureTombstone(tenant_id=user.tenant_id, subject_type=FeatureKind.USER, subject_id=user.user_id, deleted_at=AS_OF)],
    )

    assert not any(item.subject_id == user.user_id and item.subject_type is FeatureKind.USER for item in result.records)
    assert f"{user.tenant_id}:user:{user.user_id}" in result.deleted_subjects
    assert result.manifest()["record_count"] == len(result.records)


def test_consent_and_safe_defaults_are_explicit():
    dataset, _ = _run()
    denied = next(item for item in dataset.users if item.consent_state is ConsentState.PERSONALIZATION_DENIED)
    result = FeatureMaterializer().materialize((denied,), (), (), as_of=AS_OF)
    records = [item for item in result.records if item.subject_id == denied.user_id]

    assert records
    assert all(item.consent_state is ConsentState.PERSONALIZATION_DENIED for item in records)
    assert all(value == 0.0 for item in records for value in item.values.values())


def test_rejects_naive_as_of():
    dataset, _ = _run()
    with pytest.raises(ValueError, match="as_of must be timezone-aware"):
        FeatureMaterializer().materialize(dataset.users, dataset.experiences, (), as_of=datetime(2026, 1, 1))
