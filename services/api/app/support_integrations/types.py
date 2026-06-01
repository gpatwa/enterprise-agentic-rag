# services/api/app/support_integrations/types.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional


class SupportProvider(str, Enum):
    ZENDESK = "zendesk"
    INTERCOM = "intercom"


class SupportAuthMode(str, Enum):
    NANGO = "nango"
    DIRECT_ENV = "direct_env"


class SupportConnectionStatus(str, Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"
    DISABLED = "disabled"


@dataclass(frozen=True)
class SupportCatalogEntry:
    provider: str
    display_name: str
    description: str
    category: str
    auth_modes: tuple[str, ...]
    nango_provider_config_key: str
    direct_env_vars: tuple[str, ...]
    objects: tuple[str, ...]
    docs_url: Optional[str] = None


@dataclass(frozen=True)
class SupportTicketPreview:
    id: str
    subject: str
    status: Optional[str]
    requester: Optional[str]
    updated_at: Optional[str]
    url: Optional[str]
    raw: dict[str, Any]
