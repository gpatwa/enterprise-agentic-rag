"""Deterministic point-in-time feature materialization.

The materializer consumes canonical synthetic records and interaction events,
then emits rebuildable feature snapshots.  It deliberately keeps features as
provider-neutral numeric maps: downstream rankers can choose their own typed
projection without making a feature store authoritative.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState, ExperienceRecord, UserProfile
from app.events.models import EventType, InteractionEvent

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_MAX_RECORDS = 10_000
_MAX_FEATURES = 128


class FeatureKind(str, Enum):
    USER = "user"
    ITEM = "item"
    CONTEXT = "context"
    SOCIAL = "social"
    POPULARITY = "popularity"
    RETENTION = "retention"


class _FeatureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class FeatureTombstone(_FeatureModel):
    """A deletion input that suppresses a subject during a rebuild."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)
    subject_type: FeatureKind
    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)
    deleted_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "FeatureTombstone":
        _require_aware(self.deleted_at, "deleted_at")
        return self


class FeatureRecord(_FeatureModel):
    """One versioned feature vector with its temporal and privacy metadata."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)
    subject_type: FeatureKind
    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)
    feature_version: str = Field(default="v1", min_length=1, max_length=128, pattern=_VERSION_PATTERN)
    as_of: datetime
    source_watermark: datetime
    feature_age_seconds: float = Field(ge=0, le=31_536_000, allow_inf_nan=False)
    consent_state: ConsentState
    synthetic: bool
    values: dict[str, float] = Field(max_length=_MAX_FEATURES)

    @model_validator(mode="after")
    def validate_record(self) -> "FeatureRecord":
        _require_aware(self.as_of, "as_of")
        _require_aware(self.source_watermark, "source_watermark")
        if self.source_watermark > self.as_of:
            raise ValueError("source_watermark must not be after as_of")
        if any(not key or len(key) > 128 for key in self.values):
            raise ValueError("feature names must be non-empty and at most 128 characters")
        return self

    def serialize(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


class FeatureMaterialization(_FeatureModel):
    """The deterministic output and receipt for one rebuild."""

    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION_PATTERN)
    as_of: datetime
    source_watermark: datetime
    records: tuple[FeatureRecord, ...] = Field(max_length=_MAX_RECORDS)
    deleted_subjects: tuple[str, ...] = Field(max_length=_MAX_RECORDS)
    records_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_timestamps(self) -> "FeatureMaterialization":
        _require_aware(self.as_of, "as_of")
        _require_aware(self.source_watermark, "source_watermark")
        if self.source_watermark > self.as_of:
            raise ValueError("source_watermark must not be after as_of")
        return self

    def manifest(self) -> dict[str, object]:
        """Return a stable, JSON-safe rebuild manifest."""
        return {
            "feature_version": self.feature_version,
            "as_of": self.as_of.isoformat(),
            "source_watermark": self.source_watermark.isoformat(),
            "record_count": len(self.records),
            "deleted_subjects": list(self.deleted_subjects),
            "records_checksum": self.records_checksum,
        }


class FeatureMaterializer:
    """Build bounded user/item/context/social/popularity/retention snapshots."""

    def __init__(self, *, feature_version: str = "v1", max_records: int = _MAX_RECORDS) -> None:
        if not 1 <= max_records <= _MAX_RECORDS:
            raise ValueError(f"max_records must be between 1 and {_MAX_RECORDS}")
        self.feature_version = feature_version
        self.max_records = max_records

    def materialize(
        self,
        users: Sequence[UserProfile],
        experiences: Sequence[ExperienceRecord],
        events: Iterable[InteractionEvent],
        *,
        as_of: datetime,
        source_watermark: datetime | None = None,
        tombstones: Iterable[FeatureTombstone] = (),
    ) -> FeatureMaterialization:
        _require_aware(as_of, "as_of")
        watermark = source_watermark or as_of
        _require_aware(watermark, "source_watermark")
        if watermark > as_of:
            raise ValueError("source_watermark must not be after as_of")
        user_list = tuple(users)
        experience_list = tuple(experiences)
        event_list = tuple(events)
        self._validate_inputs(user_list, experience_list, event_list)
        tombstone_map = self._tombstones(tombstones, as_of)
        bounded_events = tuple(
            sorted((event for event in event_list if event.occurred_at <= as_of), key=lambda item: (item.occurred_at, item.event_id))
        )
        records: list[FeatureRecord] = []
        for user in sorted(user_list, key=lambda item: (item.tenant_id, item.user_id)):
            if self._deleted(tombstone_map, user.tenant_id, FeatureKind.USER, user.user_id):
                continue
            user_events = tuple(item for item in bounded_events if item.tenant_id == user.tenant_id and item.user_id == user.user_id)
            records.append(self._record(user.tenant_id, FeatureKind.USER, user.user_id, user.consent_state, user.synthetic, as_of, watermark, user_events, self._user_values(user_events)))
            records.append(self._record(user.tenant_id, FeatureKind.CONTEXT, user.user_id, user.consent_state, user.synthetic, as_of, watermark, user_events, self._context_values(user_events)))
            records.append(self._record(user.tenant_id, FeatureKind.SOCIAL, user.user_id, user.consent_state, user.synthetic, as_of, watermark, user_events, self._social_values(user_events)))
            records.append(self._record(user.tenant_id, FeatureKind.RETENTION, user.user_id, user.consent_state, user.synthetic, as_of, watermark, user_events, self._retention_values(user_events)))
        for experience in sorted(experience_list, key=lambda item: (item.tenant_id, item.experience_id)):
            if self._deleted(tombstone_map, experience.tenant_id, FeatureKind.ITEM, experience.experience_id):
                continue
            item_events = tuple(item for item in bounded_events if item.tenant_id == experience.tenant_id and item.experience_id == experience.experience_id)
            consent = self._consent(item_events)
            records.append(self._record(experience.tenant_id, FeatureKind.ITEM, experience.experience_id, consent, experience.synthetic, as_of, watermark, item_events, self._item_values(item_events)))
            records.append(self._record(experience.tenant_id, FeatureKind.POPULARITY, experience.experience_id, consent, experience.synthetic, as_of, watermark, item_events, self._popularity_values(item_events)))
        records.sort(key=lambda item: (item.tenant_id, item.subject_type.value, item.subject_id))
        if len(records) > self.max_records:
            raise ValueError(f"materialization exceeds max_records={self.max_records}")
        checksum = hashlib.sha256("\n".join(item.serialize() for item in records).encode("utf-8")).hexdigest()
        deleted = tuple(sorted(f"{tenant}:{kind.value}:{subject}" for tenant, kind, subject in tombstone_map))
        return FeatureMaterialization(feature_version=self.feature_version, as_of=as_of, source_watermark=watermark, records=tuple(records), deleted_subjects=deleted, records_checksum=checksum)

    @staticmethod
    def _validate_inputs(users: Sequence[UserProfile], experiences: Sequence[ExperienceRecord], events: Sequence[InteractionEvent]) -> None:
        if any(not item.synthetic for item in users) or any(not item.synthetic for item in experiences) or any(not item.synthetic for item in events):
            raise ValueError("feature materialization accepts synthetic records only")
        if len({(item.tenant_id, item.user_id) for item in users}) != len(users):
            raise ValueError("user identities must be unique")
        if len({(item.tenant_id, item.experience_id) for item in experiences}) != len(experiences):
            raise ValueError("experience identities must be unique")
        if len({item.event_id for item in events}) != len(events):
            raise ValueError("event IDs must be unique")

    @staticmethod
    def _tombstones(items: Iterable[FeatureTombstone], as_of: datetime) -> dict[tuple[str, FeatureKind, str], FeatureTombstone]:
        result: dict[tuple[str, FeatureKind, str], FeatureTombstone] = {}
        for item in items:
            if item.deleted_at <= as_of:
                key = (item.tenant_id, item.subject_type, item.subject_id)
                prior = result.get(key)
                if prior is None or item.deleted_at > prior.deleted_at:
                    result[key] = item
        return result

    @staticmethod
    def _deleted(tombstones: dict[tuple[str, FeatureKind, str], FeatureTombstone], tenant: str, kind: FeatureKind, subject: str) -> bool:
        return (tenant, kind, subject) in tombstones

    def _record(self, tenant: str, kind: FeatureKind, subject: str, consent: ConsentState, synthetic: bool, as_of: datetime, watermark: datetime, events: Sequence[InteractionEvent], values: dict[str, float]) -> FeatureRecord:
        latest = max((event.occurred_at for event in events), default=watermark)
        age = max(0.0, (as_of - latest).total_seconds())
        return FeatureRecord(tenant_id=tenant, subject_type=kind, subject_id=subject, feature_version=self.feature_version, as_of=as_of, source_watermark=watermark, feature_age_seconds=age, consent_state=consent, synthetic=synthetic, values=dict(sorted(values.items())))

    @staticmethod
    def _counts(events: Sequence[InteractionEvent], *types: EventType) -> int:
        accepted = set(types)
        return sum(event.event_type in accepted for event in events)

    def _user_values(self, events: Sequence[InteractionEvent]) -> dict[str, float]:
        return {"events": float(len(events)), "clicks": float(self._counts(events, EventType.CLICK)), "plays": float(self._counts(events, EventType.PLAY)), "playtime_seconds": sum(_payload_number(event, "duration_seconds") for event in events if event.event_type is EventType.PLAYTIME)}

    def _item_values(self, events: Sequence[InteractionEvent]) -> dict[str, float]:
        return {"impressions": float(self._counts(events, EventType.IMPRESSION)), "detail_views": float(self._counts(events, EventType.DETAIL_VIEW)), "plays": float(self._counts(events, EventType.PLAY)), "qualified_plays": float(self._counts(events, EventType.QUALIFIED_PLAY)), "saves": float(self._counts(events, EventType.SAVE)), "dismissals": float(self._counts(events, EventType.DISMISS))}

    def _popularity_values(self, events: Sequence[InteractionEvent]) -> dict[str, float]:
        impressions = self._counts(events, EventType.IMPRESSION)
        plays = self._counts(events, EventType.PLAY)
        qualified = self._counts(events, EventType.QUALIFIED_PLAY)
        return {
            "impressions": float(impressions),
            "plays": float(plays),
            "qualified_plays": float(qualified),
            "play_rate": float(plays / impressions) if impressions else 0.0,
            "qualified_play_rate": float(qualified / impressions) if impressions else 0.0,
        }

    def _context_values(self, events: Sequence[InteractionEvent]) -> dict[str, float]:
        surfaces = {str(getattr(event.payload, "surface", "")) for event in events}
        return {"event_count": float(len(events)), "surface_count": float(len(surfaces)), "search_events": float(sum(getattr(event.payload, "surface", None) == "search" for event in events))}

    def _social_values(self, events: Sequence[InteractionEvent]) -> dict[str, float]:
        return {"co_play_events": float(self._counts(events, EventType.CO_PLAY)), "invites": float(self._counts(events, EventType.INVITE)), "social_events": float(self._counts(events, EventType.CO_PLAY, EventType.INVITE))}

    def _retention_values(self, events: Sequence[InteractionEvent]) -> dict[str, float]:
        retention = [event for event in events if event.event_type is EventType.RETENTION]
        retained = sum(bool(getattr(event.payload, "retained", False)) for event in retention)
        return {"retention_events": float(len(retention)), "retained_events": float(retained), "return_events": float(self._counts(events, EventType.RETURN))}

    @staticmethod
    def _consent(events: Sequence[InteractionEvent]) -> ConsentState:
        if any(event.consent_state is ConsentState.PERSONALIZATION_DENIED for event in events):
            return ConsentState.PERSONALIZATION_DENIED
        return ConsentState.PERSONALIZATION_ALLOWED


def materialize_features(*args, **kwargs) -> FeatureMaterialization:
    """Convenience wrapper for the default v1 materializer."""
    return FeatureMaterializer().materialize(*args, **kwargs)


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _payload_number(event: InteractionEvent, field_name: str) -> float:
    value = getattr(event.payload, field_name, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0
