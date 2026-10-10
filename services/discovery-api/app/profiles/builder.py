"""Deterministic, consent-aware short- and long-term discovery profiles."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from enum import Enum
from typing import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState, ExplicitPreferences
from app.events.models import EventType, InteractionEvent

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MAX_EVENTS = 10_000
_MAX_SIGNALS = 32
_MAX_DIGESTS = 64


class _ProfileModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ProfileKind(str, Enum):
    PERSONALIZED = "personalized"
    NO_PERSONALIZATION = "no-personalization"


class ProfileWindow(_ProfileModel):
    """Bounded aggregate signals; event history and identifiers are omitted."""

    event_count: int = Field(ge=0, le=_MAX_EVENTS)
    signals: dict[str, float] = Field(max_length=_MAX_SIGNALS)

    @model_validator(mode="after")
    def validate_signals(self) -> "ProfileWindow":
        if any(not key or len(key) > 64 for key in self.signals):
            raise ValueError("profile signal names must be non-empty and bounded")
        if any(not math.isfinite(value) or value < 0 for value in self.signals.values()):
            raise ValueError("profile signals must be finite and non-negative")
        return self


class NegativeFeedback(_ProfileModel):
    dismissals: int = Field(ge=0, le=_MAX_EVENTS)
    reports: int = Field(ge=0, le=_MAX_EVENTS)
    experience_digests: tuple[str, ...] = Field(max_length=_MAX_DIGESTS)


class RetentionSignals(_ProfileModel):
    retention_events: int = Field(ge=0, le=_MAX_EVENTS)
    retained_events: int = Field(ge=0, le=_MAX_EVENTS)
    return_events: int = Field(ge=0, le=_MAX_EVENTS)
    retention_rate: float = Field(ge=0, le=1, allow_inf_nan=False)


class DiscoveryProfile(_ProfileModel):
    """Versioned profile receipt with digested scope and no raw history."""

    schema_version: str = "v1"
    profile_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    profile_kind: ProfileKind
    tenant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    as_of: datetime
    source_watermark: datetime
    consent_state: ConsentState
    short_term: ProfileWindow
    long_term: ProfileWindow
    explicit_preferences: tuple[str, ...] = Field(max_length=40)
    negative_feedback: NegativeFeedback
    retention: RetentionSignals
    deleted_event_count: int = Field(ge=0, le=_MAX_EVENTS)
    synthetic: bool
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_timestamps(self) -> "DiscoveryProfile":
        _aware(self.as_of, "as_of")
        _aware(self.source_watermark, "source_watermark")
        if self.source_watermark > self.as_of:
            raise ValueError("source_watermark must not be after as_of")
        if self.profile_kind is ProfileKind.NO_PERSONALIZATION:
            if self.explicit_preferences or any(self.short_term.signals.values()) or any(self.long_term.signals.values()):
                raise ValueError("no-personalization profiles must contain zero personal signals")
        return self

    def payload(self) -> dict[str, object]:
        value = self.model_dump(mode="json")
        value.pop("checksum", None)
        return value


class ProfileBuilder:
    """Build a bounded point-in-time profile from already validated events."""

    def __init__(
        self,
        *,
        profile_version: str = "v1",
        short_half_life_days: float = 7.0,
        long_half_life_days: float = 90.0,
        max_events: int = _MAX_EVENTS,
    ) -> None:
        if not 1 <= max_events <= _MAX_EVENTS:
            raise ValueError(f"max_events must be between 1 and {_MAX_EVENTS}")
        if short_half_life_days <= 0 or long_half_life_days <= 0 or short_half_life_days > long_half_life_days:
            raise ValueError("profile half-lives must be positive and ordered")
        self.profile_version = profile_version
        self.short_half_life_days = short_half_life_days
        self.long_half_life_days = long_half_life_days
        self.max_events = max_events

    def build(
        self,
        *,
        tenant_id: str,
        user_id: str,
        events: Iterable[InteractionEvent],
        as_of: datetime,
        consent_state: ConsentState = ConsentState.PERSONALIZATION_ALLOWED,
        explicit_preferences: ExplicitPreferences | None = None,
        deleted_event_ids: Iterable[str] = (),
        source_watermark: datetime | None = None,
    ) -> DiscoveryProfile:
        _aware(as_of, "as_of")
        watermark = source_watermark or as_of
        _aware(watermark, "source_watermark")
        if watermark > as_of:
            raise ValueError("source_watermark must not be after as_of")
        supplied = tuple(events)
        if len(supplied) > self.max_events:
            raise ValueError(f"events exceed max_events={self.max_events}")
        deleted = frozenset(deleted_event_ids)
        selected = self._select_events(supplied, tenant_id, user_id, as_of, deleted)
        effective_consent = ConsentState.PERSONALIZATION_DENIED if (
            consent_state is ConsentState.PERSONALIZATION_DENIED
            or any(event.consent_state is ConsentState.PERSONALIZATION_DENIED for event in selected)
        ) else ConsentState.PERSONALIZATION_ALLOWED
        kind = ProfileKind.NO_PERSONALIZATION if effective_consent is ConsentState.PERSONALIZATION_DENIED else ProfileKind.PERSONALIZED
        if kind is ProfileKind.NO_PERSONALIZATION:
            short = _window(0, {})
            long = _window(0, {})
            preferences: tuple[str, ...] = ()
            negative = NegativeFeedback(dismissals=0, reports=0, experience_digests=())
            retention = RetentionSignals(retention_events=0, retained_events=0, return_events=0, retention_rate=0.0)
        else:
            short = self._window(selected, as_of, self.short_half_life_days)
            long = self._window(selected, as_of, self.long_half_life_days)
            preferences = _preferences(explicit_preferences)
            negative = self._negative_feedback(selected, tenant_id)
            retention = self._retention(selected)
        values = dict(
            schema_version="v1", profile_version=self.profile_version, profile_kind=kind,
            tenant_digest=_digest(tenant_id), user_digest=_digest(user_id), as_of=as_of,
            source_watermark=watermark, consent_state=effective_consent, short_term=short,
            long_term=long, explicit_preferences=preferences, negative_feedback=negative,
            retention=retention, deleted_event_count=sum(event.event_id in deleted for event in supplied),
            synthetic=all(event.synthetic for event in selected),
        )
        checksum = _checksum(values)
        return DiscoveryProfile(**values, checksum=checksum)

    def _select_events(
        self, events: Sequence[InteractionEvent], tenant_id: str, user_id: str, as_of: datetime, deleted: frozenset[str]
    ) -> tuple[InteractionEvent, ...]:
        seen: set[str] = set()
        selected: list[InteractionEvent] = []
        for event in sorted(events, key=lambda item: (item.occurred_at, item.event_id)):
            if event.tenant_id != tenant_id or event.user_id != user_id:
                raise ValueError("event does not match profile tenant/user scope")
            if event.event_id in seen:
                continue
            seen.add(event.event_id)
            if event.event_id not in deleted and event.occurred_at <= as_of:
                selected.append(event)
        return tuple(selected)

    def _window(self, events: Sequence[InteractionEvent], as_of: datetime, half_life_days: float) -> ProfileWindow:
        weights = {name: 0.0 for name in _SIGNAL_NAMES}
        for event in events:
            weight = math.exp(-math.log(2) * max(0.0, (as_of - event.occurred_at).total_seconds()) / (half_life_days * 86_400))
            for name in _event_signals(event):
                weights[name] += weight
            if event.event_type is EventType.PLAYTIME:
                weights["playtime_seconds"] += weight * float(getattr(event.payload, "duration_seconds", 0.0))
        return _window(len(events), weights)

    @staticmethod
    def _negative_feedback(events: Sequence[InteractionEvent], tenant_id: str) -> NegativeFeedback:
        feedback = tuple(event for event in events if event.event_type in {EventType.DISMISS, EventType.REPORT})
        return NegativeFeedback(
            dismissals=sum(event.event_type is EventType.DISMISS for event in feedback),
            reports=sum(event.event_type is EventType.REPORT for event in feedback),
            experience_digests=tuple(_digest(f"{tenant_id}:{event.experience_id}") for event in feedback[:_MAX_DIGESTS]),
        )

    @staticmethod
    def _retention(events: Sequence[InteractionEvent]) -> RetentionSignals:
        retention = tuple(event for event in events if event.event_type is EventType.RETENTION)
        retained = sum(bool(getattr(event.payload, "retained", False)) for event in retention)
        return RetentionSignals(
            retention_events=len(retention), retained_events=retained,
            return_events=sum(event.event_type is EventType.RETURN for event in events),
            retention_rate=retained / len(retention) if retention else 0.0,
        )


_SIGNAL_NAMES = ("impressions", "clicks", "detail_views", "plays", "qualified_plays", "playtime_seconds", "saves", "dismissals", "reports", "invites", "co_play_events", "returns", "retention_events")


def _event_signals(event: InteractionEvent) -> tuple[str, ...]:
    return {
        EventType.IMPRESSION: ("impressions",), EventType.CLICK: ("clicks",), EventType.DETAIL_VIEW: ("detail_views",),
        EventType.PLAY: ("plays",), EventType.QUALIFIED_PLAY: ("qualified_plays",), EventType.PLAYTIME: (),
        EventType.SAVE: ("saves",), EventType.DISMISS: ("dismissals",), EventType.REPORT: ("reports",),
        EventType.INVITE: ("invites",), EventType.CO_PLAY: ("co_play_events",), EventType.RETURN: ("returns",),
        EventType.RETENTION: ("retention_events",), EventType.ORGANIC_NAVIGATION: (),
    }[event.event_type]


def _window(event_count: int, signals: dict[str, float]) -> ProfileWindow:
    return ProfileWindow(event_count=event_count, signals=dict(sorted(signals.items())))


def _preferences(preferences: ExplicitPreferences | None) -> tuple[str, ...]:
    if preferences is None:
        return ()
    return tuple(sorted({*(f"genre:{item.value}" for item in preferences.genres), *(f"theme:{item.value}" for item in preferences.themes)}))


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _checksum(value: dict[str, object]) -> str:
    encoded = json.dumps(_jsonable(value), ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python"))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def build_profile(**kwargs: object) -> DiscoveryProfile:
    """Convenience wrapper for the default versioned profile builder."""
    return ProfileBuilder().build(**kwargs)  # type: ignore[arg-type]
