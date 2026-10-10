"""Provider-neutral DTOs for authoritative discovery persistence.

These models describe the PostgreSQL boundary without importing a database
driver or making derived search/feature state authoritative.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState
from app.events.models import EventType

_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_ID = Field(min_length=1, max_length=255, pattern=_ID_PATTERN)
_VERSION = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MAX_CATALOG_PAYLOAD_BYTES = 64 * 1024
_MAX_PROFILE_PAYLOAD_BYTES = 32 * 1024
_MAX_DERIVED_PAYLOAD_BYTES = 32 * 1024


class _PersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


def _validate_timestamp(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _validate_payload(payload: dict[str, Any], *, max_bytes: int, field_name: str) -> None:
    if len(payload) > 100:
        raise ValueError(f"{field_name} must contain at most 100 keys")
    try:
        encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must contain JSON-compatible values") from exc
    if len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError(f"{field_name} exceeds {max_bytes} bytes")


def _validate_temporal_range(created_at: datetime, updated_at: datetime) -> None:
    _validate_timestamp(created_at, "created_at")
    _validate_timestamp(updated_at, "updated_at")
    if updated_at < created_at:
        raise ValueError("updated_at must not precede created_at")


class CatalogPersistenceRecord(_PersistenceModel):
    """Authoritative catalog content; search projections are derived from it."""

    tenant_id: str = _ID
    experience_id: str = _ID
    creator_id: str = _ID
    record_version: str = _VERSION
    content_version: str = _VERSION
    permission_version: str = _VERSION
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = _ID
    provenance_ref: str = Field(min_length=1, max_length=255)
    synthetic: bool
    created_at: datetime
    updated_at: datetime
    authoritative_payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_record(self) -> "CatalogPersistenceRecord":
        _validate_temporal_range(self.created_at, self.updated_at)
        _validate_payload(
            self.authoritative_payload,
            max_bytes=_MAX_CATALOG_PAYLOAD_BYTES,
            field_name="authoritative_payload",
        )
        return self


class ProfilePersistenceRecord(_PersistenceModel):
    """Authoritative user profile data with an explicit consent state."""

    tenant_id: str = _ID
    user_id: str = _ID
    profile_version: str = _VERSION
    consent_state: ConsentState
    synthetic: bool
    created_at: datetime
    updated_at: datetime
    profile_payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_record(self) -> "ProfilePersistenceRecord":
        _validate_temporal_range(self.created_at, self.updated_at)
        _validate_payload(
            self.profile_payload,
            max_bytes=_MAX_PROFILE_PAYLOAD_BYTES,
            field_name="profile_payload",
        )
        return self


class InteractionEventRecord(_PersistenceModel):
    """Append-only canonical event storage with tenant-scoped idempotency."""

    tenant_id: str = _ID
    event_id: str = _ID
    idempotency_key: str = _ID
    event_version: str = _VERSION
    event_type: EventType
    user_id: str = _ID
    experience_id: str = _ID
    request_id: str = _ID
    occurred_at: datetime
    received_at: datetime
    consent_state: ConsentState
    synthetic: bool
    event_payload: dict[str, Any]

    @model_validator(mode="after")
    def validate_record(self) -> "InteractionEventRecord":
        _validate_timestamp(self.occurred_at, "occurred_at")
        _validate_timestamp(self.received_at, "received_at")
        if self.received_at < self.occurred_at:
            raise ValueError("received_at must not precede occurred_at")
        _validate_payload(self.event_payload, max_bytes=_MAX_PROFILE_PAYLOAD_BYTES, field_name="event_payload")
        return self


class DerivedVersionMetadata(_PersistenceModel):
    """Rebuild metadata for derived features, without storing search authority."""

    tenant_id: str = _ID
    subject_type: str = Field(min_length=1, max_length=64)
    subject_id: str = _ID
    derived_kind: str = Field(min_length=1, max_length=64)
    derived_version: str = _VERSION
    source_version: str = _VERSION
    generated_at: datetime
    metadata: dict[str, Any]

    @model_validator(mode="after")
    def validate_record(self) -> "DerivedVersionMetadata":
        _validate_timestamp(self.generated_at, "generated_at")
        _validate_payload(self.metadata, max_bytes=_MAX_DERIVED_PAYLOAD_BYTES, field_name="metadata")
        return self
