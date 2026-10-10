"""Provenance-gated, fixture-only catalog adapter contracts."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Iterable, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ExperienceRecord


class ProvenanceError(ValueError):
    """Raised when catalog source evidence is missing or inconsistent."""


class SourceType(str, Enum):
    """Recognized source identities; the fixture adapter accepts only FIXTURE."""

    FIXTURE = "fixture"
    FIRST_PARTY = "first_party"
    LICENSED = "licensed"
    USER_SUBMITTED = "user_submitted"


class _AdapterModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class CatalogProvenance(_AdapterModel):
    """Evidence needed to reproduce and audit one catalog record."""

    source_type: SourceType
    source_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    provenance_ref: str = Field(min_length=1, max_length=512)
    retrieved_at: datetime
    content_version: str = Field(min_length=1, max_length=128)
    synthetic: bool

    @model_validator(mode="after")
    def validate_evidence(self) -> "CatalogProvenance":
        if not self.source_id.strip() or not self.tenant_id.strip():
            raise ProvenanceError("source identity and tenant must be non-blank")
        if not self.provenance_ref.strip() or self.provenance_ref.lower() in {
            "unknown",
            "unverified",
            "none",
        }:
            raise ProvenanceError("provenance_ref must identify verifiable evidence")
        if not self.content_version.strip():
            raise ProvenanceError("content_version must be non-blank")
        if self.retrieved_at.tzinfo is None or self.retrieved_at.utcoffset() is None:
            raise ProvenanceError("retrieved_at must be timezone-aware")
        if self.synthetic and self.source_type is not SourceType.FIXTURE:
            raise ProvenanceError("synthetic records must use fixture source type")
        return self


class CatalogAdapterRecord(_AdapterModel):
    """An authoritative experience paired with its source evidence."""

    experience: ExperienceRecord
    provenance: CatalogProvenance

    @model_validator(mode="after")
    def validate_scope(self) -> "CatalogAdapterRecord":
        if self.experience.tenant_id != self.provenance.tenant_id:
            raise ProvenanceError("experience and provenance tenant IDs must match")
        if self.experience.synthetic != self.provenance.synthetic:
            raise ProvenanceError("experience and provenance synthetic flags must match")
        return self


class CatalogAdapter(Protocol):
    """Bounded provider-neutral reads from an authoritative catalog source."""

    def get_experience(self, tenant_id: str, experience_id: str) -> CatalogAdapterRecord | None:
        """Return one record only when it belongs to the requested tenant."""

    def list_experiences(self, tenant_id: str, limit: int = 100) -> tuple[CatalogAdapterRecord, ...]:
        """Return a deterministic, bounded page for one tenant."""


class FixtureCatalogAdapter:
    """Read explicit in-memory fixtures without any network-capable dependency."""

    def __init__(
        self,
        records: Iterable[CatalogAdapterRecord],
        *,
        require_synthetic: bool = True,
        max_records: int = 1_000,
    ) -> None:
        if not 1 <= max_records <= 1_000:
            raise ValueError("max_records must be between 1 and 1,000")
        materialized = tuple(records)
        if len(materialized) > max_records:
            raise ValueError("fixture catalog exceeds max_records")
        for record in materialized:
            self._validate_fixture_record(record, require_synthetic=require_synthetic)
        identifiers = [record.experience.experience_id for record in materialized]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("fixture experience IDs must be unique")
        self._records = tuple(sorted(materialized, key=lambda item: item.experience.experience_id))
        self._require_synthetic = require_synthetic
        self._max_records = max_records

    @staticmethod
    def _validate_fixture_record(
        record: CatalogAdapterRecord, *, require_synthetic: bool
    ) -> None:
        if record.provenance.source_type is not SourceType.FIXTURE:
            raise ProvenanceError("fixture adapter accepts only fixture source type")
        if require_synthetic and not record.provenance.synthetic:
            raise ProvenanceError("fixture mode requires synthetic catalog records")
        if record.provenance.synthetic != record.experience.synthetic:
            raise ProvenanceError("record synthetic state does not match provenance")

    def get_experience(self, tenant_id: str, experience_id: str) -> CatalogAdapterRecord | None:
        if not tenant_id.strip() or not experience_id.strip():
            raise ValueError("tenant_id and experience_id must be non-blank")
        return next(
            (
                record
                for record in self._records
                if record.provenance.tenant_id == tenant_id
                and record.experience.experience_id == experience_id
            ),
            None,
        )

    def list_experiences(self, tenant_id: str, limit: int = 100) -> tuple[CatalogAdapterRecord, ...]:
        if not tenant_id.strip():
            raise ValueError("tenant_id must be non-blank")
        if not 1 <= limit <= min(self._max_records, 1_000):
            raise ValueError("limit is outside the configured bounds")
        return tuple(
            record
            for record in self._records
            if record.provenance.tenant_id == tenant_id
        )[:limit]


__all__ = [
    "CatalogAdapter",
    "CatalogAdapterRecord",
    "CatalogProvenance",
    "FixtureCatalogAdapter",
    "ProvenanceError",
    "SourceType",
]
