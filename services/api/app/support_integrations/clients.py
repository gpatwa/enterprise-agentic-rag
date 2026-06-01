# services/api/app/support_integrations/clients.py
from __future__ import annotations

import base64
from typing import Any

import httpx

from app.config import settings
from app.support_integrations.nango import NangoClient
from app.support_integrations.types import SupportTicketPreview


class ConnectorConfigError(RuntimeError):
    pass


def _zendesk_base_url(subdomain: str) -> str:
    if subdomain.startswith(("http://", "https://")):
        return subdomain.rstrip("/")
    return f"https://{subdomain}.zendesk.com"


class ZendeskDirectClient:
    def __init__(
        self,
        *,
        subdomain: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
    ) -> None:
        self.subdomain = subdomain or settings.ZENDESK_SUBDOMAIN
        self.email = email or settings.ZENDESK_EMAIL
        self.api_token = api_token or settings.ZENDESK_API_TOKEN
        self.timeout = settings.SUPPORT_CONNECTOR_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self.subdomain and self.email and self.api_token)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise ConnectorConfigError(
                "ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN are required"
            )
        token = base64.b64encode(
            f"{self.email}/token:{self.api_token}".encode("utf-8")
        ).decode("ascii")
        return {"Authorization": f"Basic {token}", "Accept": "application/json"}

    async def list_tickets(self, *, limit: int = 10) -> list[SupportTicketPreview]:
        params = {
            "per_page": min(max(limit, 1), 100),
            "sort_by": "updated_at",
            "sort_order": "desc",
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                f"{_zendesk_base_url(self.subdomain or '')}/api/v2/tickets.json",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        return [_zendesk_ticket_to_preview(t) for t in data.get("tickets", [])]

    async def test(self) -> dict[str, Any]:
        tickets = await self.list_tickets(limit=1)
        return {"ok": True, "sample_count": len(tickets)}


class IntercomDirectClient:
    def __init__(self, *, access_token: str | None = None) -> None:
        self.access_token = access_token or settings.INTERCOM_ACCESS_TOKEN
        self.timeout = settings.SUPPORT_CONNECTOR_TIMEOUT_SECONDS

    @property
    def configured(self) -> bool:
        return bool(self.access_token)

    def _headers(self) -> dict[str, str]:
        if not self.configured:
            raise ConnectorConfigError("INTERCOM_ACCESS_TOKEN is required")
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Intercom-Version": "2.13",
        }

    async def list_tickets(self, *, limit: int = 10) -> list[SupportTicketPreview]:
        params = {"per_page": min(max(limit, 1), 100)}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.get(
                "https://api.intercom.io/conversations",
                headers=self._headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
        conversations = data.get("conversations", [])
        return [_intercom_conversation_to_preview(c) for c in conversations]

    async def test(self) -> dict[str, Any]:
        tickets = await self.list_tickets(limit=1)
        return {"ok": True, "sample_count": len(tickets)}


class ZendeskNangoClient:
    def __init__(self, *, connection_id: str, provider_config_key: str) -> None:
        self.connection_id = connection_id
        self.provider_config_key = provider_config_key
        self.nango = NangoClient()

    async def list_tickets(self, *, limit: int = 10) -> list[SupportTicketPreview]:
        data = await self.nango.proxy_get(
            connection_id=self.connection_id,
            provider_config_key=self.provider_config_key,
            path="/api/v2/tickets.json",
            params={
                "per_page": min(max(limit, 1), 100),
                "sort_by": "updated_at",
                "sort_order": "desc",
            },
        )
        return [_zendesk_ticket_to_preview(t) for t in data.get("tickets", [])]

    async def test(self) -> dict[str, Any]:
        await self.nango.get_connection(
            connection_id=self.connection_id,
            provider_config_key=self.provider_config_key,
        )
        tickets = await self.list_tickets(limit=1)
        return {"ok": True, "sample_count": len(tickets)}


class IntercomNangoClient:
    def __init__(self, *, connection_id: str, provider_config_key: str) -> None:
        self.connection_id = connection_id
        self.provider_config_key = provider_config_key
        self.nango = NangoClient()

    async def list_tickets(self, *, limit: int = 10) -> list[SupportTicketPreview]:
        data = await self.nango.proxy_get(
            connection_id=self.connection_id,
            provider_config_key=self.provider_config_key,
            path="/conversations",
            params={"per_page": min(max(limit, 1), 100)},
        )
        return [_intercom_conversation_to_preview(c) for c in data.get("conversations", [])]

    async def test(self) -> dict[str, Any]:
        await self.nango.get_connection(
            connection_id=self.connection_id,
            provider_config_key=self.provider_config_key,
        )
        tickets = await self.list_tickets(limit=1)
        return {"ok": True, "sample_count": len(tickets)}


def _zendesk_ticket_to_preview(ticket: dict[str, Any]) -> SupportTicketPreview:
    ticket_id = str(ticket.get("id", ""))
    return SupportTicketPreview(
        id=ticket_id,
        subject=ticket.get("subject") or ticket.get("raw_subject") or "(no subject)",
        status=ticket.get("status"),
        requester=str(ticket.get("requester_id")) if ticket.get("requester_id") else None,
        updated_at=ticket.get("updated_at"),
        url=ticket.get("url"),
        raw=ticket,
    )


def _intercom_conversation_to_preview(conversation: dict[str, Any]) -> SupportTicketPreview:
    source = conversation.get("source") or {}
    subject = (
        source.get("subject")
        or source.get("body")
        or conversation.get("title")
        or "(no subject)"
    )
    return SupportTicketPreview(
        id=str(conversation.get("id", "")),
        subject=_compact(subject),
        status=conversation.get("state") or conversation.get("status"),
        requester=_intercom_requester(conversation),
        updated_at=_intercom_timestamp(conversation.get("updated_at")),
        url=None,
        raw=conversation,
    )


def _intercom_requester(conversation: dict[str, Any]) -> str | None:
    source = conversation.get("source") or {}
    author = source.get("author") or {}
    return author.get("email") or author.get("name") or author.get("id")


def _intercom_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        from datetime import datetime

        return datetime.utcfromtimestamp(value).replace(microsecond=0).isoformat() + "Z"
    return str(value)


def _compact(value: str) -> str:
    text = " ".join(str(value).split())
    return text[:160] + "..." if len(text) > 160 else text
