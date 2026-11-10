"""Provider-neutral contracts shared by discovery products."""
from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _aware(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value


class _DiscoveryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class DiscoveryRequestContext(_DiscoveryModel):
    """The bounded identity and request context used by every discovery call."""

    schema_version: Literal["v1"] = "v1"
    tenant_id: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    purpose: Literal["search", "home", "recommendation", "related"]
    locale: str = Field(min_length=2, max_length=32)
    device: Literal["web", "mobile", "tablet", "tv", "api"]
    age: int | None = Field(default=None, ge=0, le=150)
    consent: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    groups: tuple[str, ...] = Field(default_factory=tuple, max_length=50)
    context: tuple[tuple[str, str], ...] = Field(default_factory=tuple, max_length=30)

    @model_validator(mode="after")
    def validate_values(self) -> "DiscoveryRequestContext":
        if any(not value.strip() for value in (self.tenant_id, self.principal_id, self.request_id)):
            raise ValueError("tenant, principal, and request identifiers must be non-empty")
        if any(not value.strip() for value in self.consent + self.groups):
            raise ValueError("consent and group values must be non-empty")
        if any(not key.strip() or not value.strip() for key, value in self.context):
            raise ValueError("context keys and values must be non-empty")
        if len({key for key, _ in self.context}) != len(self.context):
            raise ValueError("context keys must be unique")
        return self


class DiscoveryComponentVersion(_DiscoveryModel):
    """A provider-independent schema, artifact, model, or policy identity."""

    component_type: Literal["schema", "artifact", "model", "policy", "feature", "embedding", "index"]
    name: str = Field(min_length=1, max_length=255)
    version: str = Field(min_length=1, max_length=255)
    digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_names(self) -> "DiscoveryComponentVersion":
        if not self.name.strip() or not self.version.strip():
            raise ValueError("component name and version must be non-empty")
        return self


class ImpressionToken(_DiscoveryModel):
    """A signed-lineage substitute that binds an impression to one request."""

    token_version: Literal["v1"] = "v1"
    token_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    context_digest: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    issued_at: datetime
    expires_at: datetime
    schema_version: str = Field(min_length=1, max_length=255)
    components: tuple[DiscoveryComponentVersion, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_lifetime(self) -> "ImpressionToken":
        _aware(self.issued_at, "issued_at")
        _aware(self.expires_at, "expires_at")
        if self.expires_at <= self.issued_at:
            raise ValueError("expires_at must be after issued_at")
        if not self.token_id.strip() or not self.schema_version.strip():
            raise ValueError("token identifiers must be non-empty")
        return self

    @classmethod
    def for_context(
        cls,
        context: DiscoveryRequestContext,
        *,
        token_id: str,
        issued_at: datetime,
        expires_at: datetime,
        schema_version: str,
        components: tuple[DiscoveryComponentVersion, ...],
    ) -> "ImpressionToken":
        return cls(
            token_id=token_id,
            tenant_id=context.tenant_id,
            principal_id=context.principal_id,
            request_id=context.request_id,
            context_digest=_context_digest(context),
            issued_at=issued_at,
            expires_at=expires_at,
            schema_version=schema_version,
            components=components,
        )

    def validate_for(self, context: DiscoveryRequestContext) -> "ImpressionToken":
        if (
            self.tenant_id != context.tenant_id
            or self.principal_id != context.principal_id
            or self.request_id != context.request_id
            or self.context_digest != _context_digest(context)
        ):
            raise ValueError("impression token does not belong to the request context")
        return self


class _DecisionStage(_DiscoveryModel):
    stage: Literal["eligibility", "retrieval", "fusion", "pre_rank", "rank", "rerank", "fallback"]
    outcome: Literal["completed", "degraded", "skipped", "failed"]
    duration_ms: float = Field(ge=0, le=600_000, allow_inf_nan=False)
    candidate_count: int = Field(ge=0, le=1_000_000)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=20)
    components: tuple[DiscoveryComponentVersion, ...] = Field(default_factory=tuple, max_length=20)

    @model_validator(mode="after")
    def validate_finite_values(self) -> "_DecisionStage":
        if not math.isfinite(self.duration_ms):
            raise ValueError("duration_ms must be finite")
        if any(not value.strip() for value in self.reason_codes):
            raise ValueError("reason codes must be non-empty")
        return self


class DecisionTrace(_DiscoveryModel):
    """Redacted, bounded evidence for how a discovery decision was made."""

    trace_version: Literal["v1"] = "v1"
    trace_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    principal_id: str = Field(min_length=1, max_length=255)
    request_id: str = Field(min_length=1, max_length=255)
    started_at: datetime
    completed_at: datetime
    stages: tuple[_DecisionStage, ...] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_trace(self) -> "DecisionTrace":
        _aware(self.started_at, "started_at")
        _aware(self.completed_at, "completed_at")
        if self.completed_at < self.started_at:
            raise ValueError("completed_at must not precede started_at")
        if any(not value.strip() for value in (self.trace_id, self.tenant_id, self.principal_id, self.request_id)):
            raise ValueError("trace identifiers must be non-empty")
        return self


def _context_digest(context: DiscoveryRequestContext) -> str:
    payload = json.dumps(
        context.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
