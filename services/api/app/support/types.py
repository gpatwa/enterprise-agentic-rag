# services/api/app/support/types.py
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass(frozen=True)
class NormalizedSupportCustomer:
    provider: str
    external_id: str
    email: Optional[str] = None
    name: Optional[str] = None
    role: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedSupportTicket:
    provider: str
    external_id: str
    subject: str
    description: Optional[str]
    status: Optional[str]
    priority: Optional[str]
    category: Optional[str]
    channel: Optional[str]
    requester_external_id: Optional[str]
    assignee_external_id: Optional[str]
    organization_external_id: Optional[str]
    tags: list[str]
    source_url: Optional[str]
    created_at_external: Optional[datetime]
    updated_at_external: Optional[datetime]
    raw: dict[str, Any] = field(default_factory=dict)
    customer: Optional[NormalizedSupportCustomer] = None


@dataclass(frozen=True)
class NormalizedSupportComment:
    provider: str
    ticket_external_id: str
    external_id: str
    author_external_id: Optional[str]
    body_text: Optional[str]
    body_html: Optional[str]
    is_public: bool
    created_at_external: Optional[datetime]
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NormalizedSupportArticle:
    provider: str
    external_id: str
    title: str
    body_text: Optional[str]
    body_html: Optional[str]
    locale: Optional[str]
    source_url: Optional[str]
    updated_at_external: Optional[datetime]
    raw: dict[str, Any] = field(default_factory=dict)
