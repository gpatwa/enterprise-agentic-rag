from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime
from typing import Any

from app.config import settings
from app.privacy.pii import redact
from app.search.schema import SupportSearchAttributes, SupportSearchDocument

_HTML_TAG = re.compile(r"<[^>]+>")


def map_ticket(
    ticket: Any,
    *,
    permission_version: str = "acl-v1",
    redact_pii: bool | None = None,
) -> SupportSearchDocument:
    title = _text(ticket.subject) or "Untitled support ticket"
    description = _text(ticket.description)
    text_parts = [
        f"Subject: {title}",
        _label("Status", ticket.status),
        _label("Priority", ticket.priority),
        _label("Category", ticket.category),
        _label("Channel", ticket.channel),
    ]
    if description:
        text_parts.extend(["", "Customer issue:", description])
    text = "\n".join(part for part in text_parts if part).strip()
    tags = _string_list(ticket.tags)
    return _build_document(
        tenant_id=ticket.tenant_id,
        provider=ticket.provider,
        source_type="ticket",
        source_id=ticket.external_id,
        title=title,
        text=text,
        source_uri=ticket.source_url,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at_external or ticket.updated_at,
        attributes=SupportSearchAttributes(
            status=_optional_text(ticket.status),
            priority=_optional_text(ticket.priority),
            category=_optional_text(ticket.category),
            channel=_optional_text(ticket.channel),
            tags=tags,
        ),
        metadata={
            "ticket_external_id": _text(ticket.external_id),
            "status": _optional_text(ticket.status),
            "priority": _optional_text(ticket.priority),
            "category": _optional_text(ticket.category),
            "channel": _optional_text(ticket.channel),
            "tags": tags,
        },
        permission_version=permission_version,
        redact_pii=redact_pii,
    )


def map_comment(
    comment: Any,
    *,
    permission_version: str = "acl-v1",
    redact_pii: bool | None = None,
) -> SupportSearchDocument:
    body = _text(comment.body_text) or _html_to_text(comment.body_html)
    title = f"Comment on ticket {_text(comment.ticket_external_id) or 'unknown'}"
    text = "\n".join(
        [
            title,
            f"Visibility: {'public' if comment.is_public else 'internal'}",
            "",
            body or "(no comment content)",
        ]
    ).strip()
    return _build_document(
        tenant_id=comment.tenant_id,
        provider=comment.provider,
        source_type="comment",
        source_id=comment.external_id,
        title=title,
        text=text,
        source_uri=None,
        created_at=comment.created_at,
        updated_at=comment.created_at_external or comment.created_at,
        attributes=SupportSearchAttributes(),
        metadata={
            "ticket_external_id": _text(comment.ticket_external_id),
            "is_public": bool(comment.is_public),
        },
        permission_version=permission_version,
        redact_pii=redact_pii,
    )


def map_article(
    article: Any,
    *,
    permission_version: str = "acl-v1",
    redact_pii: bool | None = None,
) -> SupportSearchDocument:
    title = _text(article.title) or "Untitled knowledge article"
    body = _text(article.body_text) or _html_to_text(article.body_html)
    text = "\n".join([f"Title: {title}", "", body or "(no article content)"]).strip()
    return _build_document(
        tenant_id=article.tenant_id,
        provider=article.provider,
        source_type="article",
        source_id=article.external_id,
        title=title,
        text=text,
        source_uri=article.source_url,
        created_at=article.created_at,
        updated_at=article.updated_at_external or article.updated_at,
        attributes=SupportSearchAttributes(locale=_optional_text(article.locale)),
        metadata={"locale": _optional_text(article.locale), "article_external_id": _text(article.external_id)},
        permission_version=permission_version,
        redact_pii=redact_pii,
    )


def map_chunk(
    document: SupportSearchDocument,
    chunk_text: str | None,
    *,
    chunk_index: int,
    chunk_count: int,
    redact_pii: bool | None = None,
) -> SupportSearchDocument:
    if chunk_index < 0 or chunk_index >= chunk_count:
        raise ValueError("chunk_index must be within chunk_count")
    text = _text(chunk_text) or "(no chunk content)"
    metadata = {
        **document.metadata,
        "parent_document_id": document.document_id,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
    }
    return _build_document(
        tenant_id=document.tenant_id,
        provider=document.provider,
        source_type=f"{document.source_type}_chunk",
        source_id=f"{document.source_id}:chunk:{chunk_index}",
        title=document.title,
        text=text,
        source_uri=document.source_uri,
        created_at=document.created_at,
        updated_at=document.updated_at,
        attributes=document.attributes,
        metadata=metadata,
        permission_version=document.permission_version,
        embedding_model_version=document.embedding_model_version,
        redact_pii=redact_pii,
    )


def _build_document(
    *,
    tenant_id: str,
    provider: str,
    source_type: str,
    source_id: str,
    title: str,
    text: str,
    source_uri: str | None,
    created_at: datetime | None,
    updated_at: datetime | None,
    attributes: SupportSearchAttributes,
    metadata: dict[str, Any],
    permission_version: str,
    embedding_model_version: str | None = None,
    redact_pii: bool | None = None,
) -> SupportSearchDocument:
    tenant = _required(tenant_id, "tenant_id")
    normalized_provider = _required(provider, "provider")
    normalized_source_type = _required(source_type, "source_type")
    normalized_source_id = _required(source_id, "source_id")
    normalized_title = _text(title) or "Untitled support record"
    normalized_text = _text(text) or "(no searchable content)"
    should_redact = settings.PII_REDACTION_ENABLED if redact_pii is None else redact_pii
    if should_redact:
        normalized_title, _ = redact(normalized_title)
        normalized_text, _ = redact(normalized_text)

    canonical_content = f"{normalized_title}\n{normalized_text}"
    content_hash = hashlib.sha256(canonical_content.encode("utf-8")).hexdigest()
    return SupportSearchDocument(
        document_id=_document_id(tenant, normalized_provider, normalized_source_type, normalized_source_id),
        tenant_id=tenant,
        source_type=normalized_source_type,
        source_id=normalized_source_id,
        provider=normalized_provider,
        title=normalized_title,
        text=normalized_text,
        metadata={**metadata, "updated_at": _timestamp(updated_at)},
        acl_tokens=(f"tenant:{tenant}",),
        source_uri=source_uri,
        updated_at=updated_at,
        created_at=created_at,
        content_version=f"sha256:{content_hash}",
        permission_version=permission_version,
        embedding_model_version=embedding_model_version,
        attributes=attributes,
        content_hash=content_hash,
    )


def _document_id(tenant_id: str, provider: str, source_type: str, source_id: str) -> str:
    value = f"{tenant_id}:{provider}:{source_type}:{source_id}"
    if len(value) <= 255:
        return value
    return f"{source_type}:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    text = " ".join(html.unescape(_HTML_TAG.sub(" ", value)).split())
    return re.sub(r"\s+([.,!?;:])", r"\1", text)


def _label(label: str, value: Any) -> str:
    normalized = _text(value)
    return f"{label}: {normalized}" if normalized else ""


def _required(value: Any, field_name: str) -> str:
    normalized = _text(value)
    if not normalized:
        raise ValueError(f"{field_name} cannot be blank")
    return normalized


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _optional_text(value: Any) -> str | None:
    normalized = _text(value)
    return normalized or None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    return sorted({item.strip() for item in value if isinstance(item, str) and item.strip()})


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + ("Z" if value.tzinfo is None else "")
