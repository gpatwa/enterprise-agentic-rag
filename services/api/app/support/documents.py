# services/api/app/support/documents.py
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.config import settings
from app.support.models import SupportArticle, SupportTicket, SupportTicketComment


@dataclass(frozen=True)
class SupportIndexDocument:
    source_type: str
    source_id: str
    provider: str
    title: str
    text: str
    content_hash: str
    metadata: dict


def ticket_to_document(ticket: SupportTicket) -> SupportIndexDocument:
    tags = ", ".join(ticket.tags or []) or "none"
    parts = [
        f"Provider: {ticket.provider}",
        f"Ticket ID: {ticket.external_id}",
        f"Subject: {ticket.subject}",
        f"Status: {ticket.status or 'unknown'}",
        f"Priority: {ticket.priority or 'unknown'}",
        f"Category: {ticket.category or 'unknown'}",
        f"Channel: {ticket.channel or 'unknown'}",
        f"Tags: {tags}",
    ]
    if ticket.requester_external_id:
        parts.append(f"Requester ID: {ticket.requester_external_id}")
    if ticket.organization_external_id:
        parts.append(f"Organization ID: {ticket.organization_external_id}")
    if ticket.description:
        parts.extend(["", "Customer issue:", ticket.description])

    text = "\n".join(parts).strip()
    metadata = {
        "tenant_id": ticket.tenant_id,
        "provider": ticket.provider,
        "source_type": "ticket",
        "source_id": ticket.external_id,
        "ticket_id": ticket.id,
        "subject": ticket.subject,
        "status": ticket.status,
        "priority": ticket.priority,
        "tags": ticket.tags or [],
        "source_url": ticket.source_url,
        "updated_at_external": _dt(ticket.updated_at_external),
        "index_version": settings.SUPPORT_INDEX_VERSION,
    }
    return SupportIndexDocument(
        source_type="ticket",
        source_id=ticket.external_id,
        provider=ticket.provider,
        title=ticket.subject,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata=metadata,
    )


def comment_to_document(comment: SupportTicketComment) -> SupportIndexDocument:
    body = comment.body_text or _html_to_text(comment.body_html or "")
    text = "\n".join(
        [
            f"Provider: {comment.provider}",
            f"Ticket ID: {comment.ticket_external_id}",
            f"Comment ID: {comment.external_id}",
            f"Public: {'yes' if comment.is_public else 'no'}",
            "",
            "Support conversation:",
            body or "(empty comment)",
        ]
    ).strip()
    metadata = {
        "tenant_id": comment.tenant_id,
        "provider": comment.provider,
        "source_type": "comment",
        "source_id": comment.external_id,
        "ticket_external_id": comment.ticket_external_id,
        "comment_id": comment.id,
        "is_public": comment.is_public,
        "created_at_external": _dt(comment.created_at_external),
        "index_version": settings.SUPPORT_INDEX_VERSION,
    }
    return SupportIndexDocument(
        source_type="comment",
        source_id=comment.external_id,
        provider=comment.provider,
        title=f"Comment on ticket {comment.ticket_external_id}",
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata=metadata,
    )


def article_to_document(article: SupportArticle) -> SupportIndexDocument:
    body = article.body_text or _html_to_text(article.body_html or "")
    text = "\n".join(
        [
            f"Provider: {article.provider}",
            f"Article ID: {article.external_id}",
            f"Title: {article.title}",
            f"Locale: {article.locale or 'unknown'}",
            "",
            "Knowledge base article:",
            body or "(empty article)",
        ]
    ).strip()
    metadata = {
        "tenant_id": article.tenant_id,
        "provider": article.provider,
        "source_type": "article",
        "source_id": article.external_id,
        "article_id": article.id,
        "title": article.title,
        "locale": article.locale,
        "source_url": article.source_url,
        "updated_at_external": _dt(article.updated_at_external),
        "index_version": settings.SUPPORT_INDEX_VERSION,
    }
    return SupportIndexDocument(
        source_type="article",
        source_id=article.external_id,
        provider=article.provider,
        title=article.title,
        text=text,
        content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        metadata=metadata,
    )


def chunk_text(text: str, *, chunk_chars: int | None = None, overlap_chars: int | None = None) -> list[str]:
    chunk_size = chunk_chars or settings.SUPPORT_INDEX_CHUNK_CHARS
    overlap = overlap_chars if overlap_chars is not None else settings.SUPPORT_INDEX_CHUNK_OVERLAP_CHARS
    chunk_size = max(chunk_size, 200)
    overlap = max(min(overlap, chunk_size // 2), 0)

    compact = text.strip()
    if not compact:
        return []
    if len(compact) <= chunk_size:
        return [compact]

    chunks: list[str] = []
    start = 0
    while start < len(compact):
        end = min(start + chunk_size, len(compact))
        if end < len(compact):
            boundary = max(compact.rfind("\n", start, end), compact.rfind(". ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunks.append(compact[start:end].strip())
        if end >= len(compact):
            break
        start = max(end - overlap, start + 1)
    return [chunk for chunk in chunks if chunk]


def _dt(value) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"


def _html_to_text(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return " ".join(text.split())
