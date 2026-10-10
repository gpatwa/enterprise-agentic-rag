"""Redacted, deterministic telemetry for local immersive discovery."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.discovery import DiscoveryComponentVersion

_DIGEST = r"^[0-9a-f]{64}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_LABEL = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
_MAX_COMPONENTS = 20
_MAX_MISSING_FIELDS = 20


class _TelemetryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", frozen=True, strict=True, protected_namespaces=()
    )


class TelemetryStage(str, Enum):
    """Bounded stages that may emit discovery telemetry."""

    ELIGIBILITY = "eligibility"
    RETRIEVAL = "retrieval"
    FUSION = "fusion"
    PRE_RANK = "pre_rank"
    RANK = "rank"
    RERANK = "rerank"
    FALLBACK = "fallback"
    END_TO_END = "end_to_end"


class TelemetryOutcome(str, Enum):
    """Outcome vocabulary kept stable for local evidence and dashboards."""

    COMPLETED = "completed"
    DEGRADED = "degraded"
    SKIPPED = "skipped"
    FAILED = "failed"


class LatencyBucket(str, Enum):
    """Coarse latency buckets avoid exposing precise request timing."""

    LT_10_MS = "lt_10ms"
    MS_10_TO_49 = "10_to_49ms"
    MS_50_TO_99 = "50_to_99ms"
    MS_100_TO_249 = "100_to_249ms"
    MS_250_TO_999 = "250_to_999ms"
    GE_1000_MS = "gte_1000ms"


class TelemetryEvent(_TelemetryModel):
    """One bounded event containing only digests and safe dimensions."""

    schema_version: str = Field(default="v1", pattern=_VERSION)
    event_id: str = Field(pattern=_DIGEST)
    occurred_at: datetime
    stage: TelemetryStage
    cohort: str = Field(default="all", min_length=1, max_length=64, pattern=_LABEL)
    outcome: TelemetryOutcome
    latency_bucket: LatencyBucket
    tenant_digest: str = Field(pattern=_DIGEST)
    request_digest: str = Field(pattern=_DIGEST)
    trace_digest: str | None = Field(default=None, pattern=_DIGEST)
    component_versions: tuple[DiscoveryComponentVersion, ...] = Field(
        default_factory=tuple, max_length=_MAX_COMPONENTS
    )
    policy_version: str | None = Field(default=None, max_length=128, pattern=_VERSION)
    model_version: str | None = Field(default=None, max_length=128, pattern=_VERSION)
    quality_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    feature_age_seconds: float | None = Field(default=None, ge=0, le=31_536_000, allow_inf_nan=False)
    candidate_count: int = Field(default=0, ge=0, le=1_000_000)
    missing_fields: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_MISSING_FIELDS)

    @model_validator(mode="after")
    def validate_event(self) -> "TelemetryEvent":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if any(not field.strip() for field in self.missing_fields):
            raise ValueError("missing field names must be non-empty")
        if len(set(self.missing_fields)) != len(self.missing_fields):
            raise ValueError("missing field names must be unique")
        for value in (self.quality_score, self.feature_age_seconds):
            if value is not None and not math.isfinite(value):
                raise ValueError("telemetry numeric values must be finite")
        if self.outcome is TelemetryOutcome.FAILED and self.stage is TelemetryStage.END_TO_END:
            if not self.missing_fields and self.quality_score is not None:
                raise ValueError("failed events must identify missing data or omit quality")
        return self

    def serialize(self) -> str:
        """Return stable JSON safe for a local evidence sink."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class TelemetryAggregate(_TelemetryModel):
    """Deterministic aggregate keyed by stage, cohort, outcome, and latency."""

    stage: TelemetryStage
    cohort: str = Field(min_length=1, max_length=64, pattern=_LABEL)
    outcome: TelemetryOutcome
    latency_bucket: LatencyBucket
    component_versions: tuple[str, ...] = Field(max_length=_MAX_COMPONENTS)
    event_count: int = Field(ge=0, le=1_000_000_000)
    missing_data_count: int = Field(ge=0, le=1_000_000_000)
    mean_quality_score: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    mean_feature_age_seconds: float | None = Field(default=None, ge=0, le=31_536_000, allow_inf_nan=False)


def digest(value: str) -> str:
    """Hash an identifier before it enters telemetry."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("digest input must be a non-empty string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def latency_bucket(latency_ms: float) -> LatencyBucket:
    """Map finite latency to a coarse, stable bucket."""
    if not isinstance(latency_ms, (int, float)) or isinstance(latency_ms, bool):
        raise ValueError("latency_ms must be numeric")
    if not math.isfinite(latency_ms) or latency_ms < 0 or latency_ms > 600_000:
        raise ValueError("latency_ms must be finite and between 0 and 600000")
    if latency_ms < 10:
        return LatencyBucket.LT_10_MS
    if latency_ms < 50:
        return LatencyBucket.MS_10_TO_49
    if latency_ms < 100:
        return LatencyBucket.MS_50_TO_99
    if latency_ms < 250:
        return LatencyBucket.MS_100_TO_249
    if latency_ms < 1_000:
        return LatencyBucket.MS_250_TO_999
    return LatencyBucket.GE_1000_MS


class TelemetryAggregator:
    """Collect bounded events and produce order-independent aggregates."""

    def __init__(self) -> None:
        self._events: dict[str, TelemetryEvent] = {}

    def record(self, event: TelemetryEvent) -> bool:
        """Insert an event idempotently; return whether it was newly accepted."""
        existing = self._events.get(event.event_id)
        if existing is not None:
            if existing != event:
                raise ValueError("event_id already exists with different telemetry")
            return False
        self._events[event.event_id] = event
        return True

    def aggregate(self) -> tuple[TelemetryAggregate, ...]:
        buckets: dict[tuple[object, ...], list[TelemetryEvent]] = {}
        for event in self._events.values():
            key = (
                event.stage,
                event.cohort,
                event.outcome,
                event.latency_bucket,
                tuple(sorted(f"{item.name}:{item.version}" for item in event.component_versions)),
            )
            buckets.setdefault(key, []).append(event)
        rows: list[TelemetryAggregate] = []
        for key, events in sorted(buckets.items(), key=lambda item: tuple(str(value) for value in item[0])):
            quality = [event.quality_score for event in events if event.quality_score is not None]
            ages = [event.feature_age_seconds for event in events if event.feature_age_seconds is not None]
            rows.append(
                TelemetryAggregate(
                    stage=key[0], cohort=key[1], outcome=key[2], latency_bucket=key[3],
                    component_versions=key[4], event_count=len(events),
                    missing_data_count=sum(bool(event.missing_fields) for event in events),
                    mean_quality_score=sum(quality) / len(quality) if quality else None,
                    mean_feature_age_seconds=sum(ages) / len(ages) if ages else None,
                )
            )
        return tuple(rows)

    def serialize(self) -> str:
        return json.dumps([row.model_dump(mode="json") for row in self.aggregate()], sort_keys=True, separators=(",", ":"))


class NoOpTelemetrySink:
    """Local default sink that validates and intentionally discards events."""

    def emit(self, event: TelemetryEvent) -> None:
        if not isinstance(event, TelemetryEvent):
            raise TypeError("sink accepts TelemetryEvent values")


def aggregate_events(events: Iterable[TelemetryEvent]) -> tuple[TelemetryAggregate, ...]:
    """Aggregate an iterable without depending on iteration order."""
    aggregator = TelemetryAggregator()
    for event in events:
        aggregator.record(event)
    return aggregator.aggregate()


__all__ = [
    "LatencyBucket",
    "NoOpTelemetrySink",
    "TelemetryAggregate",
    "TelemetryAggregator",
    "TelemetryEvent",
    "TelemetryOutcome",
    "TelemetryStage",
    "aggregate_events",
    "digest",
    "latency_bucket",
]
