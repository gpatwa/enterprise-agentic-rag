"""Provider-neutral mapping from catalog records to search documents."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import ExperienceRecord
from app.search.mapping import CatalogMappingVersions


class CatalogDocumentMappingError(ValueError):
    """Raised when a catalog record cannot be safely mapped for indexing."""


class CatalogDocumentInput(BaseModel):
    """Authorized metadata and derived signals needed to build one document."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    record: ExperienceRecord
    tenant_id: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=255)
    source_id: str = Field(min_length=1, max_length=255)
    provenance_ref: str = Field(min_length=1, max_length=255)
    content_version: str = Field(min_length=1, max_length=255)
    permission_version: str = Field(min_length=1, max_length=255)
    embedding: tuple[float, ...] = Field(min_length=1, max_length=4096)
    blocked: bool = False
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mapping_versions: CatalogMappingVersions = Field(default_factory=CatalogMappingVersions)

    @field_validator("tenant_id", "source_type", "source_id", "provenance_ref", "content_version", "permission_version")
    @classmethod
    def reject_blank_metadata(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("metadata values must be non-blank")
        return value

    @field_validator("embedding")
    @classmethod
    def validate_embedding_values(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(not isinstance(item, (int, float)) or isinstance(item, bool) for item in value):
            raise ValueError("embedding values must be numeric")
        return tuple(float(item) for item in value)

    @model_validator(mode="after")
    def validate_scope_and_versions(self) -> "CatalogDocumentInput":
        if self.record.tenant_id != self.tenant_id:
            raise ValueError("record tenant does not match document tenant")
        if self.blocked:
            raise ValueError("blocked records cannot be mapped")
        if len(self.embedding) != self.mapping_versions.embedding_dimensions:
            raise ValueError("embedding dimension is not supported by the mapping")
        if self.updated_at < self.created_at:
            raise ValueError("updated_at cannot precede created_at")
        return self


class CatalogSearchDocument(BaseModel):
    """Strict document payload matching the IMD-021 catalog mapping."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    experience_id: str
    experience_id_normalized: str
    creator_id: str
    tenant_id: str
    title: str
    description: str
    tags: tuple[str, ...]
    genres: tuple[str, ...]
    themes: tuple[str, ...]
    mechanics: tuple[str, ...]
    locales: tuple[str, ...]
    devices: tuple[str, ...]
    age_rating: str
    safety_state: str
    availability: str
    blocked: bool
    source_type: str
    source_id: str
    provenance_ref: str
    content_version: str
    permission_version: str
    created_at: datetime
    updated_at: datetime
    freshness_band: str
    quality_band: str
    popularity_band: str
    signals_version: str
    modality: str
    exposure_key: str
    synthetic: bool
    embedding: tuple[float, ...]

    def stable_json(self) -> str:
        """Serialize with sorted keys and stable JSON values."""
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


def map_catalog_document(source: CatalogDocumentInput) -> CatalogSearchDocument:
    """Map an authorized catalog input without contacting a search provider."""
    record = source.record
    if record.safety_state.value != "approved" or record.availability.value != "available":
        raise CatalogDocumentMappingError("blocked or unavailable records cannot be indexed")
    if source.mapping_versions.embedding_dimensions != len(source.embedding):
        raise CatalogDocumentMappingError("embedding dimension is not supported by the mapping")

    genres = _stable_values(record.genres)
    themes = _stable_values(record.themes)
    mechanics = _stable_values(record.mechanics)
    tags = tuple(sorted(set(genres + themes + mechanics)))
    document = CatalogSearchDocument(
        experience_id=record.experience_id,
        experience_id_normalized=_normalize_id(record.experience_id),
        creator_id=record.creator_id,
        tenant_id=record.tenant_id,
        title=record.title,
        description=record.description,
        tags=tags,
        genres=genres,
        themes=themes,
        mechanics=mechanics,
        locales=_stable_values(record.locales),
        devices=_stable_values(record.devices),
        age_rating=record.age_rating.value,
        safety_state=record.safety_state.value,
        availability=record.availability.value,
        blocked=False,
        source_type=source.source_type,
        source_id=source.source_id,
        provenance_ref=source.provenance_ref,
        content_version=source.content_version,
        permission_version=source.permission_version,
        created_at=_utc(source.created_at),
        updated_at=_utc(source.updated_at),
        freshness_band=record.signals.freshness_band.value if record.signals else "steady",
        quality_band=record.signals.quality_band.value if record.signals else "medium",
        popularity_band=record.signals.popularity_band.value if record.signals else "niche",
        signals_version=record.signals.signals_version if record.signals else "none",
        modality="text",
        exposure_key=_document_id(source.tenant_id, record.experience_id),
        synthetic=record.synthetic,
        embedding=source.embedding,
    )
    return document


def _stable_values(values: tuple[Any, ...]) -> tuple[str, ...]:
    return tuple(sorted({str(value.value if hasattr(value, "value") else value) for value in values}))


def _normalize_id(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).lower()


def _document_id(tenant_id: str, experience_id: str) -> str:
    material = f"{tenant_id}\x00{experience_id}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
