from datetime import datetime, timedelta, timezone

import pytest

from app.domain.models import ConsentState
from app.features.hydration import (
    FeatureHydrationRequest,
    FeatureHydrator,
    HydrationStatus,
)
from app.features.materialization import FeatureKind, FeatureRecord
from packages.platform_contracts.discovery import DiscoveryRequestContext

AS_OF = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _request(**overrides):
    values = {
        "context": DiscoveryRequestContext(
            tenant_id="tenant-orbit", principal_id="user-001", request_id="req-001", purpose="recommendation", locale="en-US", device="web"
        ),
        "as_of": AS_OF,
        "feature_version": "v1",
        "subject_type": FeatureKind.USER,
        "subject_id": "user-001",
        "feature_names": ("clicks", "plays", "missing"),
    }
    values.update(overrides)
    return FeatureHydrationRequest(**values)


def _record(**overrides):
    values = {
        "tenant_id": "tenant-orbit",
        "subject_type": FeatureKind.USER,
        "subject_id": "user-001",
        "feature_version": "v1",
        "as_of": AS_OF - timedelta(minutes=2),
        "source_watermark": AS_OF - timedelta(minutes=2),
        "feature_age_seconds": 120.0,
        "consent_state": ConsentState.PERSONALIZATION_ALLOWED,
        "synthetic": True,
        "values": {"clicks": 2.0, "plays": 1.0},
    }
    values.update(overrides)
    if "as_of" in overrides and "source_watermark" not in overrides:
        values["source_watermark"] = overrides["as_of"]
    return FeatureRecord(**values)


def test_hydration_is_deterministic_and_defaults_missing_scalars():
    result = FeatureHydrator().hydrate(_request(), _record())
    assert [(item.name, item.value, item.status) for item in result.features] == [
        ("clicks", 2.0, HydrationStatus.HYDRATED),
        ("plays", 1.0, HydrationStatus.HYDRATED),
        ("missing", 0.0, HydrationStatus.DEFAULTED),
    ]
    assert result.trace.defaulted_count == 1
    assert result == FeatureHydrator().hydrate(_request(), _record())


@pytest.mark.parametrize("record_kwargs, expected", [
    ({"feature_version": "v2"}, HydrationStatus.VERSION_MISMATCH),
    ({"as_of": AS_OF + timedelta(seconds=1)}, HydrationStatus.FUTURE),
    ({"as_of": AS_OF - timedelta(hours=2)}, HydrationStatus.STALE),
])
def test_future_stale_and_mismatched_records_fail_closed(record_kwargs, expected):
    result = FeatureHydrator().hydrate(_request(), _record(**record_kwargs))
    assert result.trace.status is expected
    assert all(item.value == 0.0 for item in result.features)


def test_consent_denied_excludes_personalized_values_and_trace_is_redacted():
    result = FeatureHydrator().hydrate(_request(consent_state=ConsentState.PERSONALIZATION_DENIED), _record())
    assert result.trace.status is HydrationStatus.CONSENT_DENIED
    assert all(item.value == 0.0 for item in result.features)
    assert result.trace.tenant_digest != "tenant-orbit"
    assert result.trace.subject_digest != "user-001"


def test_identity_and_private_feature_boundaries_are_enforced():
    with pytest.raises(ValueError, match="tenant"):
        FeatureHydrator().hydrate(_request(), _record(tenant_id="tenant-other"))
    with pytest.raises(ValueError, match="private feature"):
        _request(feature_names=("embedding",))
    with pytest.raises(ValueError, match="timezone-aware"):
        _request(as_of=datetime(2026, 1, 1))
