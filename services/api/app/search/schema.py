from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from pydantic import Field, field_validator, model_validator

from app.search.models import SearchDocument, SearchModel

SUPPORT_SEARCH_SCHEMA_VERSION = "support-search-v1"
_CONTENT_HASH = re.compile(r"^[a-f0-9]{64}$")


class SupportSearchAttributes(SearchModel):
    """Typed support fields used for filtering and ranking."""

    status: str | None = Field(default=None, max_length=64)
    priority: str | None = Field(default=None, max_length=64)
    category: str | None = Field(default=None, max_length=128)
    channel: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=32)
    tags: tuple[str, ...] = ()

    @field_validator("tags", mode="before")
    @classmethod
    def _normalize_tags(cls, value: Any) -> tuple[str, ...]:
        if value is None:
            return ()
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("tags must be a sequence of strings")
        return tuple(sorted({tag.strip() for tag in value if isinstance(tag, str) and tag.strip()}))


class SupportRankFeatures(SearchModel):
    """Explicit, bounded fields for future personalized ranking."""

    freshness_score: float = Field(default=0.0, ge=0.0, le=1.0)
    quality_score: float = Field(default=0.0, ge=0.0, le=1.0)
    resolution_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    popularity_score: float = Field(default=0.0, ge=0.0)
    engagement_score: float = Field(default=0.0, ge=0.0)


class SupportSearchDocument(SearchDocument):
    """Versioned support index document independent of OpenSearch mappings."""

    schema_version: str = SUPPORT_SEARCH_SCHEMA_VERSION
    attributes: SupportSearchAttributes = Field(default_factory=SupportSearchAttributes)
    rank_features: SupportRankFeatures = Field(default_factory=SupportRankFeatures)
    created_at: datetime | None = None
    content_hash: str = Field(min_length=64, max_length=64)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != SUPPORT_SEARCH_SCHEMA_VERSION:
            raise ValueError(f"unsupported support search schema version: {value}")
        return value

    @field_validator("content_hash")
    @classmethod
    def _validate_content_hash(cls, value: str) -> str:
        if not _CONTENT_HASH.fullmatch(value):
            raise ValueError("content_hash must be a lowercase SHA-256 hex digest")
        return value

    @model_validator(mode="after")
    def _validate_tenant_scope(self) -> SupportSearchDocument:
        if f"tenant:{self.tenant_id}" not in self.acl_tokens:
            raise ValueError("support document ACL must include the tenant scope token")
        return self
