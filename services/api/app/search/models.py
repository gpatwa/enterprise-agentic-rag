from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from math import isfinite
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_FIELD_NAME = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{0,127}$")


class SearchModel(BaseModel):
    """Immutable, backend-neutral search value object."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class SearchMode(str, Enum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"


class RetrievalSource(str, Enum):
    LEXICAL = "lexical"
    VECTOR = "vector"
    HYBRID = "hybrid"


class FilterOperator(str, Enum):
    EQ = "eq"
    NE = "ne"
    IN = "in"
    NOT_IN = "not_in"
    PREFIX = "prefix"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"


class SearchScope(SearchModel):
    """Identity and authorization context required for every search."""

    tenant_id: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    acl_tokens: tuple[str, ...] = Field(min_length=1)

    @field_validator("tenant_id", "principal_id", "purpose", mode="before")
    @classmethod
    def _normalize_required_text(cls, value: Any) -> str:
        if not isinstance(value, str):
            raise ValueError("scope values must be strings")
        normalized = value.strip()
        if not normalized:
            raise ValueError("scope values cannot be blank")
        return normalized

    @field_validator("acl_tokens", mode="before")
    @classmethod
    def _normalize_acl_tokens(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("acl_tokens must be a sequence of strings")
        tokens = {token.strip() for token in value if isinstance(token, str) and token.strip()}
        if not tokens:
            raise ValueError("acl_tokens must contain at least one token")
        return tuple(sorted(tokens))

    @model_validator(mode="after")
    def _require_tenant_acl_token(self) -> SearchScope:
        required_token = f"tenant:{self.tenant_id}"
        if required_token not in self.acl_tokens:
            raise ValueError("acl_tokens must include the tenant scope token")
        return self


class SearchFilter(SearchModel):
    field: str = Field(min_length=1, max_length=128)
    operator: FilterOperator = FilterOperator.EQ
    value: Any

    @field_validator("field")
    @classmethod
    def _validate_field(cls, value: str) -> str:
        normalized = value.strip()
        if not _FIELD_NAME.fullmatch(normalized):
            raise ValueError("filter field contains unsupported characters")
        return normalized


class SearchRequest(SearchModel):
    text: str = Field(min_length=1, max_length=4000)
    scope: SearchScope
    mode: SearchMode = SearchMode.HYBRID
    filters: tuple[SearchFilter, ...] = ()
    limit: int = Field(default=10, ge=1, le=100)
    cursor: str | None = Field(default=None, max_length=4096)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    query_vector: tuple[float, ...] | None = None
    request_id: str | None = Field(default=None, max_length=255)

    @field_validator("text")
    @classmethod
    def _normalize_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("search text cannot be blank")
        return normalized

    @field_validator("query_vector", mode="before")
    @classmethod
    def _normalize_query_vector(cls, value: Any) -> tuple[float, ...] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or not value:
            raise ValueError("query_vector must be a non-empty sequence")
        vector = tuple(float(item) for item in value)
        if not all(isfinite(item) for item in vector):
            raise ValueError("query_vector values must be finite")
        return vector


class RankingExplanation(SearchModel):
    sources: tuple[RetrievalSource, ...] = ()
    components: dict[str, float] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @field_validator("components")
    @classmethod
    def _validate_components(cls, value: dict[str, float]) -> dict[str, float]:
        if any(not key.strip() for key in value):
            raise ValueError("ranking component names cannot be blank")
        return {key.strip(): float(score) for key, score in value.items()}


class SearchDocument(SearchModel):
    """Canonical document shape supplied to a search provider."""

    document_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=2000)
    text: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
    acl_tokens: tuple[str, ...] = Field(min_length=1)
    vector: tuple[float, ...] | None = None
    source_uri: str | None = None
    updated_at: datetime | None = None
    content_version: str = Field(min_length=1, max_length=255)
    permission_version: str = Field(default="unknown", min_length=1, max_length=255)
    embedding_model_version: str | None = Field(default=None, max_length=255)

    @field_validator("acl_tokens", mode="before")
    @classmethod
    def _normalize_document_acl_tokens(cls, value: Any) -> tuple[str, ...]:
        if not isinstance(value, (list, tuple, set, frozenset)):
            raise ValueError("acl_tokens must be a sequence of strings")
        tokens = {token.strip() for token in value if isinstance(token, str) and token.strip()}
        if not tokens:
            raise ValueError("acl_tokens must contain at least one token")
        return tuple(sorted(tokens))

    @field_validator("vector")
    @classmethod
    def _validate_vector(cls, value: tuple[float, ...] | None) -> tuple[float, ...] | None:
        if value is not None and not value:
            raise ValueError("vector cannot be empty")
        return value


class SearchResult(SearchModel):
    document_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    source_type: str = Field(min_length=1, max_length=64)
    source_id: str = Field(min_length=1, max_length=255)
    title: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    score: float = Field(ge=0.0)
    rank: int = Field(ge=1)
    retrieval_source: RetrievalSource
    lexical_score: float | None = None
    vector_score: float | None = None
    fusion_score: float | None = None
    highlights: tuple[str, ...] = ()
    source_uri: str | None = None
    index_generation: str = Field(min_length=1, max_length=255)
    content_version: str = Field(min_length=1, max_length=255)
    permission_version: str = Field(min_length=1, max_length=255)
    embedding_model_version: str | None = None
    explanation: RankingExplanation | None = None


class SearchResponse(SearchModel):
    results: tuple[SearchResult, ...] = ()
    total: int = Field(default=0, ge=0)
    next_cursor: str | None = None
    index_alias: str = Field(min_length=1, max_length=255)
    index_generation: str = Field(min_length=1, max_length=255)


class SearchIndexSpec(SearchModel):
    alias: str = Field(min_length=1, max_length=255)
    generation: str = Field(min_length=1, max_length=255)
    schema_version: str = Field(min_length=1, max_length=255)
    vector_dimensions: int = Field(ge=1, le=10000)
    embedding_model_version: str = Field(min_length=1, max_length=255)


class SearchHealth(SearchModel):
    status: str = Field(min_length=1, max_length=32)
    index_alias: str = Field(min_length=1, max_length=255)
    index_generation: str | None = None
    document_count: int = Field(default=0, ge=0)
    details: dict[str, Any] = Field(default_factory=dict)


class SearchWriteError(SearchModel):
    document_id: str = Field(min_length=1, max_length=255)
    code: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=2000)
    retryable: bool = False


class BulkWriteResult(SearchModel):
    attempted: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    errors: tuple[SearchWriteError, ...] = ()

    @model_validator(mode="after")
    def _validate_counts(self) -> BulkWriteResult:
        if self.succeeded + self.failed != self.attempted:
            raise ValueError("succeeded plus failed must equal attempted")
        if len(self.errors) != self.failed:
            raise ValueError("errors must contain one entry per failed document")
        return self
