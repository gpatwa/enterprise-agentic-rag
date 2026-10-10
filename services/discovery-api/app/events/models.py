"""Immutable, provider-neutral interaction events for immersive discovery."""
from __future__ import annotations

import json
import math
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState
from packages.platform_contracts.discovery import ImpressionToken

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_ID = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)


def _aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _nonblank(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-empty")


class _EventModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EventType(str, Enum):
    IMPRESSION = "impression"
    CLICK = "click"
    DETAIL_VIEW = "detail_view"
    PLAY = "play"
    QUALIFIED_PLAY = "qualified_play"
    PLAYTIME = "playtime"
    SAVE = "save"
    DISMISS = "dismiss"
    REPORT = "report"
    INVITE = "invite"
    CO_PLAY = "co_play"
    RETURN = "return"
    RETENTION = "retention"
    ORGANIC_NAVIGATION = "organic_navigation"


class NavigationPath(str, Enum):
    ORGANIC = "organic"
    DIRECT = "direct_navigation"


class OrganicNavigationPayload(_EventModel):
    path: NavigationPath
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    destination: Literal["experience"] = "experience"


class ImpressionPayload(_EventModel):
    position: int = Field(ge=0, le=1_000_000)
    surface: Literal["search", "home", "recommendation", "related"]
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    result_set_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)


class ClickPayload(_EventModel):
    position: int | None = Field(default=None, ge=0, le=1_000_000)
    target: Literal["card", "title", "thumbnail", "primary_action"] = "card"


class DetailViewPayload(_EventModel):
    entry_point: Literal["search", "home", "recommendation", "related", "direct"]
    dwell_seconds: float | None = Field(default=None, ge=0, le=86_400, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_finite(self) -> "DetailViewPayload":
        if self.dwell_seconds is not None and not math.isfinite(self.dwell_seconds):
            raise ValueError("dwell_seconds must be finite")
        return self


class PlayPayload(_EventModel):
    launch_source: Literal["card", "detail", "direct"]
    session_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)


class QualifiedPlayPayload(_EventModel):
    duration_seconds: float = Field(gt=0, le=86_400, allow_inf_nan=False)
    qualification_threshold_seconds: float = Field(gt=0, le=86_400, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_values(self) -> "QualifiedPlayPayload":
        if not math.isfinite(self.duration_seconds) or not math.isfinite(self.qualification_threshold_seconds):
            raise ValueError("qualified-play durations must be finite")
        if self.duration_seconds < self.qualification_threshold_seconds:
            raise ValueError("duration_seconds must meet the qualification threshold")
        return self


class PlaytimePayload(_EventModel):
    duration_seconds: float = Field(gt=0, le=86_400, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_finite(self) -> "PlaytimePayload":
        if not math.isfinite(self.duration_seconds):
            raise ValueError("duration_seconds must be finite")
        return self


class SavePayload(_EventModel):
    collection: str | None = Field(default=None, min_length=1, max_length=255)


class DismissPayload(_EventModel):
    reason: Literal["not_interested", "already_seen", "too_complex", "not_relevant", "other"]


class ReportPayload(_EventModel):
    category: Literal["safety", "copyright", "spam", "misleading", "other"]


class InvitePayload(_EventModel):
    recipient_count: int = Field(gt=0, le=100)
    channel: Literal["in_app", "link", "group"]


class CoPlayPayload(_EventModel):
    participant_count: int = Field(ge=2, le=100)
    session_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)


class ReturnPayload(_EventModel):
    days_since_prior_play: int = Field(gt=0, le=36_500)


class RetentionPayload(_EventModel):
    horizon: Literal["D1", "D7", "D28"]
    retained: bool


EventPayload = Annotated[
    Union[
        ImpressionPayload,
        ClickPayload,
        DetailViewPayload,
        PlayPayload,
        QualifiedPlayPayload,
        PlaytimePayload,
        SavePayload,
        DismissPayload,
        ReportPayload,
        InvitePayload,
        CoPlayPayload,
        ReturnPayload,
        RetentionPayload,
        OrganicNavigationPayload,
    ],
    Field(discriminator=None),
]


_PAYLOAD_TYPES: dict[EventType, type[BaseModel]] = {
    EventType.IMPRESSION: ImpressionPayload,
    EventType.CLICK: ClickPayload,
    EventType.DETAIL_VIEW: DetailViewPayload,
    EventType.PLAY: PlayPayload,
    EventType.QUALIFIED_PLAY: QualifiedPlayPayload,
    EventType.PLAYTIME: PlaytimePayload,
    EventType.SAVE: SavePayload,
    EventType.DISMISS: DismissPayload,
    EventType.REPORT: ReportPayload,
    EventType.INVITE: InvitePayload,
    EventType.CO_PLAY: CoPlayPayload,
    EventType.RETURN: ReturnPayload,
    EventType.RETENTION: RetentionPayload,
    EventType.ORGANIC_NAVIGATION: OrganicNavigationPayload,
}

_RECOMMENDATION_ACTIONS = frozenset(EventType) - {EventType.ORGANIC_NAVIGATION}


class InteractionEvent(_EventModel):
    """A versioned action whose lineage cannot be silently fabricated."""

    schema_version: Literal["v1"] = "v1"
    event_version: Literal["v1"] = "v1"
    event_id: str = _ID
    event_type: EventType
    tenant_id: str = _ID
    user_id: str = _ID
    experience_id: str = _ID
    request_id: str = _ID
    occurred_at: datetime
    synthetic: bool
    consent_state: ConsentState
    impression_token: ImpressionToken | None = None
    payload: EventPayload

    @model_validator(mode="after")
    def validate_contract(self) -> "InteractionEvent":
        _aware(self.occurred_at, "occurred_at")
        for value, name in (
            (self.event_id, "event_id"),
            (self.tenant_id, "tenant_id"),
            (self.user_id, "user_id"),
            (self.experience_id, "experience_id"),
            (self.request_id, "request_id"),
        ):
            _nonblank(value, name)

        expected_payload = _PAYLOAD_TYPES[self.event_type]
        if not isinstance(self.payload, expected_payload):
            raise ValueError(f"payload does not match event_type {self.event_type.value}")

        if self.event_type is EventType.ORGANIC_NAVIGATION:
            if self.impression_token is not None:
                raise ValueError("organic navigation cannot carry an impression token")
            if self.payload.path not in {NavigationPath.ORGANIC, NavigationPath.DIRECT}:
                raise ValueError("organic navigation must use an explicit navigation path")
            return self

        if self.impression_token is None:
            raise ValueError("recommendation events require an impression token")
        if self.impression_token.tenant_id != self.tenant_id:
            raise ValueError("impression token tenant does not match event")
        if self.impression_token.principal_id != self.user_id:
            raise ValueError("impression token user does not match event")
        if self.impression_token.request_id != self.request_id:
            raise ValueError("impression token request does not match event")
        return self

    def serialize(self) -> str:
        """Return canonical JSON for fixtures, hashes, and append-only records."""
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )


class InteractionEventBatch(_EventModel):
    """A bounded, strictly ordered batch suitable for deterministic processing."""

    schema_version: Literal["v1"] = "v1"
    batch_id: str = _ID
    events: tuple[InteractionEvent, ...] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_order(self) -> "InteractionEventBatch":
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event IDs must be unique within a batch")
        sort_keys = [(event.occurred_at, event.event_id) for event in self.events]
        if sort_keys != sorted(sort_keys) or any(left == right for left, right in zip(sort_keys, sort_keys[1:])):
            raise ValueError("events must be supplied in strict occurred_at/event_id order")
        return self

    def serialize(self) -> str:
        return json.dumps(
            self.model_dump(mode="json"),
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
