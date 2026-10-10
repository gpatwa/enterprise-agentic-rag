"""Local-only, append-only audit evidence for ranking decisions."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from enum import Enum
from typing import Any, Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_DIGEST = r"^[0-9a-f]{64}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_CODE = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
_MAX_CANDIDATES = 500
_MAX_REASONS = 16
_MAX_COMPONENTS = 32
_MAX_EVIDENCE = 32
_SENSITIVE = re.compile(
    r"(?:query|prompt|history|vector|embedding|social|provider|payload|secret|token|password|email|phone|address|ip|identity|raw)",
    re.IGNORECASE,
)


class _AuditModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class AuditOutcome(str, Enum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    REJECTED = "rejected"
    FAILED = "failed"


class PolicyOutcome(str, Enum):
    ALLOWED = "allowed"
    FILTERED = "filtered"
    DENIED = "denied"
    UNKNOWN = "unknown"


class RankingAuditRecord(_AuditModel):
    """One immutable, redacted ranking decision receipt."""

    schema_version: str = Field(default="v1", min_length=1, max_length=128, pattern=_VERSION)
    event_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_digest: str = Field(pattern=_DIGEST)
    request_digest: str = Field(pattern=_DIGEST)
    decision_digest: str = Field(pattern=_DIGEST)
    outcome: AuditOutcome
    eligibility_outcome: PolicyOutcome
    policy_outcome: PolicyOutcome
    fallback: bool = False
    candidate_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    eligible_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    selected_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)
    component_versions: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_COMPONENTS)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_EVIDENCE)
    occurred_at: datetime
    record_checksum: str = Field(pattern=_DIGEST)

    @model_validator(mode="after")
    def validate_record(self) -> "RankingAuditRecord":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.eligible_count > self.candidate_count or self.selected_count > self.eligible_count:
            raise ValueError("ranking counts must be monotonic")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        if any(not _CODE_RE.fullmatch(value) for value in self.reason_codes):
            raise ValueError("reason codes must be bounded labels")
        if any(not _VERSION_RE.fullmatch(value) for value in self.component_versions):
            raise ValueError("component versions must be bounded labels")
        if any(not _CODE_RE.fullmatch(value) or _SENSITIVE.search(value) for value in self.evidence):
            raise ValueError("evidence must be redacted bounded labels")
        if self.outcome is AuditOutcome.FAILED and not self.reason_codes:
            raise ValueError("failed decisions require a redacted reason")
        return self

    def serialize(self) -> str:
        """Return canonical JSON suitable for local evidence export."""
        return _serialize(self.model_dump(mode="json"))


_CODE_RE = re.compile(_CODE)
_VERSION_RE = re.compile(_VERSION)


class RankingAuditWriter:
    """Append-only local writer with idempotent event and readback behavior."""

    def __init__(self, *, enabled: bool = True, max_records: int = 10_000) -> None:
        if isinstance(enabled, bool) is False:
            raise ValueError("enabled must be boolean")
        if isinstance(max_records, bool) or not 1 <= max_records <= 10_000:
            raise ValueError("max_records must be between 1 and 10000")
        self.enabled = enabled
        self.max_records = max_records
        self._records: dict[str, RankingAuditRecord] = {}

    @property
    def records(self) -> tuple[RankingAuditRecord, ...]:
        """Return deterministic readback without exposing mutable storage."""
        return tuple(self._records[event_id] for event_id in sorted(self._records))

    def append(self, record: RankingAuditRecord) -> bool:
        """Append once; identical retries are accepted as no-ops."""
        if not isinstance(record, RankingAuditRecord):
            raise TypeError("writer accepts RankingAuditRecord values")
        if not self.enabled:
            return False
        existing = self._records.get(record.event_id)
        if existing is not None:
            if existing != record:
                raise ValueError("event_id already exists with different audit evidence")
            return False
        if len(self._records) >= self.max_records:
            raise ValueError("audit writer capacity exceeded")
        self._records[record.event_id] = record
        return True

    def append_many(self, records: Iterable[RankingAuditRecord]) -> int:
        """Append a bounded batch, preserving idempotent retry semantics."""
        values = tuple(records)
        if len(values) > self.max_records:
            raise ValueError("audit batch exceeds writer capacity")
        accepted = 0
        for record in values:
            accepted += int(self.append(record))
        return accepted

    def readback(self) -> tuple[RankingAuditRecord, ...]:
        return self.records

    def serialize(self) -> str:
        return _serialize([record.model_dump(mode="json") for record in self.records])


class NoOpRankingAuditWriter(RankingAuditWriter):
    """Explicit local no-op writer that validates but retains no records."""

    def __init__(self) -> None:
        super().__init__(enabled=False)


def digest(value: str) -> str:
    """Hash an identifier before it enters audit evidence."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("digest input must be a non-empty string")
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def checksum(value: Any) -> str:
    """Compute a canonical checksum without accepting raw sensitive fields."""
    _reject_sensitive(value)
    return hashlib.sha256(_serialize(value).encode("utf-8")).hexdigest()


def _serialize(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _reject_sensitive(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if _SENSITIVE.search(str(key)):
                raise ValueError("raw sensitive fields are not permitted in audit evidence")
            _reject_sensitive(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_sensitive(item)


__all__ = [
    "AuditOutcome",
    "NoOpRankingAuditWriter",
    "PolicyOutcome",
    "RankingAuditRecord",
    "RankingAuditWriter",
    "checksum",
    "digest",
]
