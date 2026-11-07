"""Typed records for the file-based product ingest. Products are not experiences; see docs/DISCOVERY_ESCI_SCOPE.md."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

QUARANTINE_REASONS = (
    "missing_product_id",
    "empty_title",
    "title_too_long",
    "control_characters",
    "field_too_long",
    "locale_mismatch",
    "conflicting_duplicate",
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProductProvenance(_Model):
    """Where a subset came from. ``license_status`` stays ``unconfirmed`` until the owner records a decision."""

    dataset: Literal["esci", "fixture"]
    dataset_version: str = Field(min_length=1, max_length=128)
    citation: str = Field(min_length=1, max_length=512)
    license_status: Literal["unconfirmed", "confirmed_by_owner"] = "unconfirmed"
    synthetic: bool


class ProductRecord(_Model):
    product_id: str = Field(min_length=1, max_length=128)
    locale: str = Field(min_length=2, max_length=16)
    title: str = Field(min_length=1, max_length=500)
    description: str = Field(default="", max_length=20000)
    bullets: str = Field(default="", max_length=20000)
    brand: str = Field(default="", max_length=255)
    color: str = Field(default="", max_length=255)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("title must be non-blank")
        return value


class QuarantinedRow(_Model):
    """A rejected row. The reason is a fixed code; row text is never copied into it."""

    product_id: str
    reason: str


class IngestManifest(_Model):
    """Everything needed to reproduce, audit and verify one subset."""

    provenance: ProductProvenance
    locale: str
    limit: int = Field(ge=1)
    seed: int
    products_file_sha256: str
    examples_file_sha256: str
    rows_read: int = Field(ge=0)
    candidates: int = Field(ge=0)
    selected: int = Field(ge=0)
    quarantined: dict[str, int]
    subset_checksum: str
    created_at: datetime


class IngestResult(_Model):
    records: tuple[ProductRecord, ...]
    quarantine: tuple[QuarantinedRow, ...]
    manifest: IngestManifest
