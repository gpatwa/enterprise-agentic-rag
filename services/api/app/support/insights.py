# services/api/app/support/insights.py
from __future__ import annotations

import re
from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.support.models import SupportTicket
from app.support.store import support_data_store

_GENERIC_TAGS = {
    "bug",
    "customer",
    "demo",
    "high",
    "incident",
    "issue",
    "low",
    "medium",
    "question",
    "support",
    "ticket",
    "urgent",
}

_GENERIC_SUBJECT_TOKENS = {
    "after",
    "again",
    "before",
    "cannot",
    "customer",
    "does",
    "fails",
    "from",
    "into",
    "issue",
    "shows",
    "still",
    "stopped",
    "support",
    "their",
    "when",
    "with",
}


async def repeat_ticket_insights(
    session: AsyncSession,
    *,
    tenant_id: str,
    provider: str | None = None,
    status: str | None = None,
    limit: int = 200,
    min_count: int = 2,
    top_n: int = 5,
) -> dict[str, Any]:
    """Find repeat-ticket clusters from normalized support tickets.

    This intentionally uses the canonical ticket table instead of the vector
    index so local dev can show GTM value immediately after seeding demo data.
    """
    tickets, total = await support_data_store.list_tickets(
        session,
        tenant_id=tenant_id,
        provider=provider,
        status=status,
        limit=min(max(limit, 1), 200),
        offset=0,
    )
    if not tickets:
        return {
            "insights": [],
            "summary": {
                "tickets_analyzed": 0,
                "total_tickets": total,
                "repeat_clusters": 0,
                "repeat_ticket_count": 0,
                "potential_deflection_count": 0,
            },
        }

    tag_frequency = Counter(tag for ticket in tickets for tag in _normalized_tags(ticket))
    buckets: dict[str, dict[str, Any]] = {}
    for ticket in tickets:
        key, title, signals = _cluster_signature(ticket, tag_frequency)
        bucket = buckets.setdefault(
            key,
            {
                "id": key,
                "title": title,
                "signals": signals,
                "tickets": [],
            },
        )
        bucket["tickets"].append(ticket)

    insights = []
    for bucket in buckets.values():
        rows: list[SupportTicket] = bucket["tickets"]
        if len(rows) < min_count:
            continue
        insights.append(_bucket_to_insight(bucket, rows, analyzed_count=len(tickets)))

    insights.sort(
        key=lambda item: (
            item["count"],
            item["potential_deflection_count"],
            item["latest_updated_at"] or "",
        ),
        reverse=True,
    )
    insights = insights[: max(top_n, 1)]

    repeat_ticket_count = sum(item["count"] for item in insights)
    potential_deflection_count = sum(item["potential_deflection_count"] for item in insights)
    return {
        "insights": insights,
        "summary": {
            "tickets_analyzed": len(tickets),
            "total_tickets": total,
            "repeat_clusters": len(insights),
            "repeat_ticket_count": repeat_ticket_count,
            "potential_deflection_count": potential_deflection_count,
        },
    }


def _bucket_to_insight(
    bucket: dict[str, Any],
    rows: list[SupportTicket],
    *,
    analyzed_count: int,
) -> dict[str, Any]:
    rows_by_recent = sorted(
        rows,
        key=lambda ticket: ticket.updated_at_external or ticket.updated_at or datetime.min,
        reverse=True,
    )
    statuses = Counter(ticket.status or "unknown" for ticket in rows)
    priorities = Counter(ticket.priority or "unknown" for ticket in rows)
    tags = Counter(tag for ticket in rows for tag in _normalized_tags(ticket))
    providers = sorted({ticket.provider for ticket in rows if ticket.provider})
    latest = rows_by_recent[0].updated_at_external or rows_by_recent[0].updated_at
    solved_count = statuses.get("solved", 0) + statuses.get("closed", 0)
    deflection_candidate = solved_count > 0
    potential_deflection_count = max(len(rows) - 1, 0)

    return {
        "id": bucket["id"],
        "title": bucket["title"],
        "signals": bucket["signals"],
        "count": len(rows),
        "share": round(len(rows) / max(analyzed_count, 1), 4),
        "providers": providers,
        "statuses": dict(statuses),
        "priorities": dict(priorities),
        "tags": [tag for tag, _ in tags.most_common(6)],
        "latest_updated_at": _dt(latest),
        "sample_tickets": [_ticket_sample(ticket) for ticket in rows_by_recent[:3]],
        "related_query": f"How have we resolved {bucket['title'].lower()} issues?",
        "deflection_candidate": deflection_candidate,
        "potential_deflection_count": potential_deflection_count,
        "recommended_action": _recommended_action(
            count=len(rows),
            solved_count=solved_count,
            potential_deflection_count=potential_deflection_count,
        ),
    }


def _recommended_action(*, count: int, solved_count: int, potential_deflection_count: int) -> str:
    if solved_count >= 1:
        return (
            f"Package the solved evidence into a macro/help article and use it to deflect "
            f"up to {potential_deflection_count} repeat ticket{'s' if potential_deflection_count != 1 else ''}."
        )
    if count >= 3:
        return "Route this cluster to support ops and product because repeats exist without a proven resolution."
    return "Keep monitoring; this needs another solved example before safe automation."


def _cluster_signature(ticket: SupportTicket, tag_frequency: Counter[str]) -> tuple[str, str, list[str]]:
    tags = _normalized_tags(ticket)
    if tags:
        ranked = sorted(
            dict.fromkeys(tags),
            key=lambda tag: (-tag_frequency[tag], tags.index(tag), tag),
        )
        repeated_tags = [tag for tag in ranked if tag_frequency[tag] > 1]
        signature_tags = repeated_tags[:2]
        if not signature_tags:
            signature_tags = ranked[:2]
        if signature_tags:
            key = "tag:" + "|".join(signature_tags)
            return key, _title_from_signals(signature_tags), signature_tags

    tokens = _subject_tokens(ticket.subject)
    if tokens:
        signature_tokens = tokens[:2]
        key = "subject:" + "|".join(signature_tokens)
        return key, _title_from_signals(signature_tokens), signature_tokens

    category = (ticket.category or "uncategorized").strip().lower()
    return f"category:{category}", category.replace("-", " ").title(), [category]


def _normalized_tags(ticket: SupportTicket) -> list[str]:
    tags = ticket.tags or []
    normalized = []
    for tag in tags:
        value = str(tag).strip().lower().replace("_", "-")
        if not value or value in _GENERIC_TAGS:
            continue
        normalized.append(value)
    return normalized


def _subject_tokens(subject: str | None) -> list[str]:
    values = []
    for token in re.findall(r"[a-z0-9][a-z0-9-]{2,}", (subject or "").lower()):
        if token in _GENERIC_SUBJECT_TOKENS:
            continue
        values.append(token)
    return list(dict.fromkeys(values))


def _title_from_signals(signals: list[str]) -> str:
    return " + ".join(signal.replace("-", " ").title() for signal in signals)


def _ticket_sample(ticket: SupportTicket) -> dict[str, Any]:
    return {
        "provider": ticket.provider,
        "external_id": ticket.external_id,
        "subject": ticket.subject,
        "status": ticket.status,
        "priority": ticket.priority,
        "source_url": ticket.source_url,
        "updated_at_external": _dt(ticket.updated_at_external),
    }


def _dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(microsecond=0).isoformat() + "Z"
