"""Focused contract tests for redacted discovery telemetry."""
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.telemetry.discovery import (
    LatencyBucket,
    NoOpTelemetrySink,
    TelemetryAggregator,
    TelemetryEvent,
    TelemetryOutcome,
    TelemetryStage,
    aggregate_events,
    digest,
    latency_bucket,
)


def _event(event_id: str = "1" * 64, *, quality: float | None = 0.8) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=event_id,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        stage=TelemetryStage.RANK,
        cohort="new_user",
        outcome=TelemetryOutcome.COMPLETED,
        latency_bucket=latency_bucket(75),
        tenant_digest=digest("tenant-a"),
        request_digest=digest("request-a"),
        quality_score=quality,
        feature_age_seconds=30,
        candidate_count=12,
    )


def test_event_is_redacted_and_serialization_is_stable() -> None:
    event = _event()
    serialized = event.serialize()
    assert "tenant-a" not in serialized
    assert "query" not in serialized
    assert serialized == event.serialize()


def test_raw_sensitive_fields_and_non_finite_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TelemetryEvent(**{**_event().model_dump(), "query_text": "private query"})
    with pytest.raises(ValidationError):
        TelemetryEvent(**{**_event().model_dump(), "quality_score": float("nan")})
    with pytest.raises(ValueError):
        latency_bucket(float("inf"))


def test_latency_buckets_are_bounded() -> None:
    assert latency_bucket(0) is LatencyBucket.LT_10_MS
    assert latency_bucket(49.9) is LatencyBucket.MS_10_TO_49
    assert latency_bucket(1_000) is LatencyBucket.GE_1000_MS


def test_aggregation_is_idempotent_and_order_independent() -> None:
    first = _event("1" * 64, quality=0.6)
    second = _event("2" * 64, quality=None)
    left = aggregate_events([first, second])
    right = aggregate_events([second, first])
    assert left == right
    assert left[0].event_count == 2
    assert left[0].mean_quality_score == pytest.approx(0.6)
    assert TelemetryAggregator().record(first) is True
    aggregator = TelemetryAggregator()
    assert aggregator.record(first) is True
    assert aggregator.record(first) is False


def test_no_op_sink_does_not_retain_data() -> None:
    sink = NoOpTelemetrySink()
    assert sink.emit(_event()) is None
    assert not hasattr(sink, "events")
