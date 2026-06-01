# services/api/app/support/normalizers.py
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.support.types import NormalizedSupportCustomer, NormalizedSupportTicket


class SupportNormalizerError(ValueError):
    pass


def normalize_ticket(provider: str, raw: dict[str, Any]) -> NormalizedSupportTicket:
    provider = provider.lower().strip()
    if provider == "zendesk":
        return normalize_zendesk_ticket(raw)
    if provider == "intercom":
        return normalize_intercom_conversation(raw)
    raise SupportNormalizerError(f"unsupported support provider: {provider}")


def normalize_zendesk_ticket(raw: dict[str, Any]) -> NormalizedSupportTicket:
    external_id = _required_id(raw.get("id"), "Zendesk ticket")
    tags = [str(tag) for tag in raw.get("tags") or [] if tag is not None]
    via = raw.get("via") or {}
    requester_id = _str_or_none(raw.get("requester_id"))

    return NormalizedSupportTicket(
        provider="zendesk",
        external_id=external_id,
        subject=_clean(raw.get("subject") or raw.get("raw_subject") or "(no subject)"),
        description=_clean_or_none(raw.get("description")),
        status=_str_or_none(raw.get("status")),
        priority=_str_or_none(raw.get("priority")),
        category=_str_or_none(raw.get("type")),
        channel=_str_or_none(via.get("channel")),
        requester_external_id=requester_id,
        assignee_external_id=_str_or_none(raw.get("assignee_id")),
        organization_external_id=_str_or_none(raw.get("organization_id")),
        tags=tags,
        source_url=_str_or_none(raw.get("url")),
        created_at_external=_parse_dt(raw.get("created_at")),
        updated_at_external=_parse_dt(raw.get("updated_at")),
        raw=raw,
        customer=(
            NormalizedSupportCustomer(
                provider="zendesk",
                external_id=requester_id,
                raw={"id": requester_id},
            )
            if requester_id
            else None
        ),
    )


def normalize_intercom_conversation(raw: dict[str, Any]) -> NormalizedSupportTicket:
    external_id = _required_id(raw.get("id"), "Intercom conversation")
    source = raw.get("source") or {}
    author = source.get("author") or {}
    requester_id = _str_or_none(author.get("id"))
    subject = source.get("subject") or source.get("body") or raw.get("title") or "(no subject)"

    return NormalizedSupportTicket(
        provider="intercom",
        external_id=external_id,
        subject=_clean(subject, limit=1000),
        description=_clean_or_none(source.get("body")),
        status=_str_or_none(raw.get("state") or raw.get("status")),
        priority=_str_or_none(raw.get("priority")),
        category=_str_or_none(raw.get("type") or raw.get("conversation_message", {}).get("type")),
        channel=_str_or_none(source.get("type") or source.get("delivered_as")),
        requester_external_id=requester_id,
        assignee_external_id=_intercom_assignee_id(raw),
        organization_external_id=None,
        tags=_intercom_tags(raw),
        source_url=None,
        created_at_external=_parse_dt(raw.get("created_at")),
        updated_at_external=_parse_dt(raw.get("updated_at")),
        raw=raw,
        customer=(
            NormalizedSupportCustomer(
                provider="intercom",
                external_id=requester_id,
                email=_str_or_none(author.get("email")),
                name=_str_or_none(author.get("name")),
                role=_str_or_none(author.get("type")),
                raw=author,
            )
            if requester_id
            else None
        ),
    )


def _intercom_assignee_id(raw: dict[str, Any]) -> str | None:
    assignee = raw.get("assignee") or {}
    return _str_or_none(assignee.get("id"))


def _intercom_tags(raw: dict[str, Any]) -> list[str]:
    tags = raw.get("tags") or {}
    items = tags.get("tags") if isinstance(tags, dict) else tags
    if not isinstance(items, list):
        return []
    values = []
    for item in items:
        if isinstance(item, dict):
            value = item.get("name") or item.get("id")
        else:
            value = item
        if value:
            values.append(str(value))
    return values


def _required_id(value: Any, label: str) -> str:
    text = _str_or_none(value)
    if not text:
        raise SupportNormalizerError(f"{label} missing id")
    return text


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean(value: Any, *, limit: int = 1000) -> str:
    text = " ".join(str(value or "").split())
    if not text:
        text = "(no subject)"
    return text[:limit]


def _clean_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _parse_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return _naive_utc(value)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).replace(tzinfo=None)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            if text.endswith("Z"):
                text = text[:-1] + "+00:00"
            return _naive_utc(datetime.fromisoformat(text))
        except ValueError:
            return None
    return None


def _naive_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)
