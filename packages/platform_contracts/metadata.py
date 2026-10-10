"""Vendor-neutral metadata snapshots used by analytics context providers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class MetadataGlossaryTerm(BaseModel):
    term_id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    source: str = Field(min_length=1, max_length=100)


class MetadataFreshness(BaseModel):
    last_updated_at: datetime | None = None
    expected_interval_seconds: int | None = Field(default=None, gt=0)
    stale: bool = False


class MetadataQualitySignals(BaseModel):
    completeness: float | None = Field(default=None, ge=0, le=1)
    null_rate: float | None = Field(default=None, ge=0, le=1)
    row_count: int | None = Field(default=None, ge=0)
    issues: list[str] = Field(default_factory=list)


class MetadataTest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    status: Literal["pass", "fail", "warn", "not_run"] = "not_run"
    failure_message: str | None = None
    executed_at: datetime | None = None


class MetadataExposure(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    exposure_type: str = Field(min_length=1, max_length=100)
    owner_ids: list[str] = Field(default_factory=list)
    url: str | None = None


class MetadataMetric(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    label: str | None = None
    expression: str | None = None
    type: str | None = None


class MetadataColumn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    data_type: str = Field(min_length=1, max_length=255)
    description: str | None = None
    nullable: bool = True
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"


class MetadataAsset(BaseModel):
    id: str = Field(min_length=1, max_length=512)
    display_name: str = Field(min_length=1, max_length=255)
    physical_name: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=100)
    description: str | None = None
    owner_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    certified: bool = False
    columns: list[MetadataColumn] = Field(default_factory=list)
    lineage_asset_ids: list[str] = Field(default_factory=list)
    upstream_asset_ids: list[str] = Field(default_factory=list)
    downstream_asset_ids: list[str] = Field(default_factory=list)
    glossary_terms: list[MetadataGlossaryTerm] = Field(default_factory=list)
    quality: MetadataQualitySignals | None = None
    freshness: MetadataFreshness | None = None
    tests: list[MetadataTest] = Field(default_factory=list)
    exposures: list[MetadataExposure] = Field(default_factory=list)
    metrics: list[MetadataMetric] = Field(default_factory=list)
    classification: Literal["public", "internal", "confidential", "restricted"] = "internal"
    source_version: str | None = None
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MetadataSnapshot(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    captured_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    assets: list[MetadataAsset] = Field(default_factory=list)


class MetadataQualityReport(BaseModel):
    asset_id: str
    score: float = Field(ge=0, le=1)
    actionable: bool
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class MetadataSearchResult(BaseModel):
    asset: MetadataAsset
    score: float = Field(ge=0)
