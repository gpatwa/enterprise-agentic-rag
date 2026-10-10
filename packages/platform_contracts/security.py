"""Identity, authorization, and tamper-evident audit contracts."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field


class AnalyticsIdentity(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=255)
    user_id: str = Field(min_length=1, max_length=255)
    purposes: list[str] = Field(default_factory=list)
    groups: list[str] = Field(default_factory=list)
    claims: dict[str, str] = Field(default_factory=dict)


class AuthorizationDecision(BaseModel):
    decision_id: str = Field(min_length=1, max_length=255)
    effect: Literal["allow", "deny", "review"]
    reasons: list[str] = Field(min_length=1)
    enforced_filter_ids: list[str] = Field(default_factory=list)
    policy_version: str = Field(min_length=1, max_length=255)


class AuditEvent(BaseModel):
    event_id: str = Field(min_length=1, max_length=255)
    event_type: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(min_length=1, max_length=255)
    actor_id: str = Field(min_length=1, max_length=255)
    payload: dict = Field(default_factory=dict)
    previous_hash: str | None = None
    event_hash: str = Field(min_length=64, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
