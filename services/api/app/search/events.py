from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import Field, field_validator, model_validator

from app.search.models import SearchModel


class InteractionKind(str, Enum):
    SEARCH = "search"
    CLICK = "click"
    OPEN = "open"
    ACCEPT = "accept"
    DISMISS = "dismiss"
    RESOLVE = "resolve"
    EDIT = "edit"
    APPROVE = "approve"
    REJECT = "reject"
    EXECUTE = "execute"
    FEEDBACK = "feedback"


class SearchInteractionEvent(SearchModel):
    schema_version: str = "search-interaction.v1"
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=255)
    idempotency_key: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    principal_pseudonym: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    kind: InteractionKind
    request_id: str | None = Field(default=None, max_length=255)
    document_id: str | None = Field(default=None, max_length=255)
    query_hash: str | None = Field(default=None, max_length=128)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: datetime
    consent_granted: bool = False
    metadata: dict[str, str] = Field(default_factory=dict)

    @field_validator("occurred_at", "expires_at", mode="before")
    @classmethod
    def _normalize_datetime(cls, value: Any) -> datetime:
        if not isinstance(value, datetime):
            raise ValueError("interaction timestamps must be datetimes")
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)

    @model_validator(mode="after")
    def _validate_retention(self) -> SearchInteractionEvent:
        if self.expires_at <= self.occurred_at:
            raise ValueError("expires_at must be after occurred_at")
        if self.expires_at - self.occurred_at > timedelta(days=730):
            raise ValueError("interaction retention cannot exceed 730 days")
        if self.kind != InteractionKind.SEARCH and not self.document_id:
            raise ValueError("document_id is required for non-search interactions")
        return self


def pseudonymize_principal(principal_id: str, *, tenant_id: str, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{tenant_id}:{principal_id}".encode("utf-8")).hexdigest()


def hash_query(query: str, *, salt: str) -> str:
    return hashlib.sha256(f"{salt}:{query.strip()}".encode("utf-8")).hexdigest()
