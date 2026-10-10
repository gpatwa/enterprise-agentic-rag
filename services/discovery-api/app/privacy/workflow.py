"""Local-only consent, retention, export, and deletion workflow."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ConsentState

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_TOKEN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{15,127}$"
_MAX_RECORDS = 10_000
_MAX_EXPORT = 1_000
_MAX_FIELDS = 20
_SENSITIVE = re.compile(r"(?:token|secret|password|email|phone|address|ip|raw|history|vector|embedding|social|identity)", re.I)


class _PrivacyModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PrivacyOperation(str, Enum):
    WITHDRAW_CONSENT = "withdraw_consent"
    RETAIN = "retain"
    EXPORT = "export"
    DELETE = "delete"


class PrivacySource(str, Enum):
    CATALOG = "canonical_catalog"
    PROFILE = "canonical_profile"
    EVENT = "canonical_event"
    EVENT_LAKE = "event_lake_partition"
    FEATURE = "feature_snapshot"
    MODEL_INPUT = "model_input"
    DERIVED_INDEX = "derived_index"

    @property
    def derived(self) -> bool:
        return self in {PrivacySource.EVENT_LAKE, PrivacySource.FEATURE, PrivacySource.MODEL_INPUT, PrivacySource.DERIVED_INDEX}


class PrivacyRecord(_PrivacyModel):
    """A bounded record descriptor; payloads are never returned in evidence."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    record_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    source: PrivacySource
    created_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict, max_length=100)

    @model_validator(mode="after")
    def validate_record(self) -> "PrivacyRecord":
        _aware(self.created_at, "created_at")
        _json_size(self.payload, 64 * 1024, "payload")
        return self


class PrivacyRequest(_PrivacyModel):
    """An explicitly authorized, bounded privacy operation."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    operation: PrivacyOperation
    consent_state: ConsentState
    requested_at: datetime
    retention_days: int = Field(ge=1, le=3650)
    confirmation_token: str = Field(min_length=16, max_length=128, pattern=_TOKEN)
    approved_export_fields: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_FIELDS)
    max_export_records: int = Field(default=_MAX_EXPORT, ge=1, le=_MAX_EXPORT)

    @model_validator(mode="after")
    def validate_request(self) -> "PrivacyRequest":
        _aware(self.requested_at, "requested_at")
        if self.operation is PrivacyOperation.WITHDRAW_CONSENT and self.consent_state is not ConsentState.PERSONALIZATION_DENIED:
            raise ValueError("consent withdrawal requires denied consent")
        if self.operation is PrivacyOperation.EXPORT and not self.approved_export_fields:
            raise ValueError("export requires approved fields")
        if any(not field or len(field) > 64 for field in self.approved_export_fields):
            raise ValueError("export fields must be approved and bounded")
        return self


class ExportRecord(_PrivacyModel):
    record_ref: str = Field(pattern=r"^[0-9a-f]{64}$")
    source: PrivacySource
    fields: dict[str, Any] = Field(max_length=_MAX_FIELDS)


class PrivacyEvidence(_PrivacyModel):
    """Append-only receipt with hashed references rather than raw identities."""

    schema_version: str = "v1"
    evidence_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    operation: PrivacyOperation
    status: str = Field(pattern=r"^(completed|rejected)$")
    tenant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    user_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    affected_count: int = Field(ge=0, le=_MAX_RECORDS)
    deleted_count: int = Field(ge=0, le=_MAX_RECORDS)
    tombstoned_count: int = Field(ge=0, le=_MAX_RECORDS)
    exported_count: int = Field(ge=0, le=_MAX_EXPORT)
    record_checksum: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_counts(self) -> "PrivacyEvidence":
        _aware(self.created_at, "created_at")
        if self.deleted_count + self.tombstoned_count > self.affected_count:
            raise ValueError("privacy action counts exceed affected records")
        return self


class PrivacyResult(_PrivacyModel):
    operation: PrivacyOperation
    status: str = Field(pattern=r"^(completed|rejected)$")
    remaining: tuple[PrivacyRecord, ...] = Field(max_length=_MAX_RECORDS)
    tombstones: tuple[str, ...] = Field(max_length=_MAX_RECORDS)
    exported: tuple[ExportRecord, ...] = Field(max_length=_MAX_EXPORT)
    evidence: PrivacyEvidence


class PrivacyWorkflow:
    """Apply privacy operations to a bounded local record set.

    The returned tombstone set is a rebuild input: derived writers must honor
    it, so deleted content cannot reappear from canonical event history.
    """

    def __init__(self, *, max_records: int = _MAX_RECORDS) -> None:
        if isinstance(max_records, bool) or not 1 <= max_records <= _MAX_RECORDS:
            raise ValueError(f"max_records must be between 1 and {_MAX_RECORDS}")
        self.max_records = max_records
        self._evidence: list[PrivacyEvidence] = []

    @property
    def evidence_log(self) -> tuple[PrivacyEvidence, ...]:
        return tuple(self._evidence)

    def execute(self, records: Iterable[PrivacyRecord], request: PrivacyRequest) -> PrivacyResult:
        values = tuple(records)
        if len(values) > self.max_records:
            raise ValueError(f"records exceed max_records={self.max_records}")
        if any(record.tenant_id != request.tenant_id for record in values):
            raise ValueError("records must be scoped to the request tenant")
        if request.operation is PrivacyOperation.RETAIN:
            return self._retain(values, request)
        selected = tuple(record for record in values if record.subject_id == request.user_id)
        if request.operation is PrivacyOperation.EXPORT:
            return self._export(values, selected, request)
        return self._mutate(values, selected, request)

    def _mutate(self, values: tuple[PrivacyRecord, ...], selected: tuple[PrivacyRecord, ...], request: PrivacyRequest) -> PrivacyResult:
        if request.operation is PrivacyOperation.WITHDRAW_CONSENT:
            removed_sources = {PrivacySource.PROFILE, PrivacySource.EVENT, PrivacySource.EVENT_LAKE, PrivacySource.MODEL_INPUT}
            tombstone_sources = {PrivacySource.FEATURE, PrivacySource.DERIVED_INDEX}
        else:
            removed_sources = set(PrivacySource)
            tombstone_sources = {source for source in PrivacySource if source.derived}
        deleted = tuple(record for record in selected if record.source in removed_sources)
        tombstoned = tuple(record for record in selected if record.source in tombstone_sources)
        affected = deleted + tuple(record for record in tombstoned if record not in deleted)
        remaining = tuple(record for record in values if record not in affected)
        return self._result(request, remaining, affected, deleted_count=len(deleted), tombstoned=tombstoned)

    def _retain(self, values: tuple[PrivacyRecord, ...], request: PrivacyRequest) -> PrivacyResult:
        cutoff = request.requested_at - timedelta(days=request.retention_days)
        selected = tuple(record for record in values if record.subject_id == request.user_id and record.created_at < cutoff)
        deleted = tuple(record for record in selected if not record.source.derived)
        tombstoned = tuple(record for record in selected if record.source.derived)
        affected = deleted + tuple(record for record in tombstoned if record not in deleted)
        remaining = tuple(record for record in values if record not in affected)
        return self._result(request, remaining, affected, deleted_count=len(deleted), tombstoned=tombstoned)

    def _export(self, values: tuple[PrivacyRecord, ...], selected: tuple[PrivacyRecord, ...], request: PrivacyRequest) -> PrivacyResult:
        exported: list[ExportRecord] = []
        for record in selected[: request.max_export_records]:
            fields = {
                field: _redact(record.payload[field])
                for field in request.approved_export_fields
                if field in record.payload and not _SENSITIVE.search(field)
            }
            exported.append(ExportRecord(record_ref=_digest(f"{record.tenant_id}:{record.record_id}"), source=record.source, fields=fields))
        checksum = _checksum([item.model_dump(mode="json") for item in exported])
        evidence = self._evidence_for(request, len(exported), 0, 0, len(exported), checksum)
        return PrivacyResult(operation=request.operation, status="completed", remaining=values, tombstones=tuple(), exported=tuple(exported), evidence=evidence)

    def _result(self, request: PrivacyRequest, remaining: tuple[PrivacyRecord, ...], affected: tuple[PrivacyRecord, ...], *, deleted_count: int, tombstoned: tuple[PrivacyRecord, ...]) -> PrivacyResult:
        tombstones = tuple(sorted(_digest(f"{record.tenant_id}:{record.source.value}:{record.record_id}") for record in tombstoned))
        checksum = _checksum(tombstones)
        evidence = self._evidence_for(request, len(affected), deleted_count, len(tombstoned), 0, checksum)
        return PrivacyResult(operation=request.operation, status="completed", remaining=remaining, tombstones=tombstones, exported=tuple(), evidence=evidence)

    def _evidence_for(self, request: PrivacyRequest, affected: int, deleted: int, tombstoned: int, exported: int, checksum: str) -> PrivacyEvidence:
        created_at = datetime.now(timezone.utc)
        evidence = PrivacyEvidence(
            evidence_id=_digest(f"{request.tenant_id}:{request.user_id}:{request.operation.value}:{created_at.isoformat()}"),
            operation=request.operation,
            status="completed",
            tenant_digest=_digest(request.tenant_id),
            user_digest=_digest(f"{request.tenant_id}:{request.user_id}"),
            affected_count=affected,
            deleted_count=deleted,
            tombstoned_count=tombstoned,
            exported_count=exported,
            record_checksum=checksum,
            created_at=created_at,
        )
        self._evidence.append(evidence)
        return evidence


def _aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _json_size(value: object, limit: int, name: str) -> None:
    try:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be JSON-compatible") from exc
    if len(encoded.encode("utf-8")) > limit:
        raise ValueError(f"{name} exceeds {limit} bytes")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _checksum(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items() if not _SENSITIVE.search(str(key))}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    return value
