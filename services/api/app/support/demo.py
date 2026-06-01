# services/api/app/support/demo.py
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.support.models import SupportSyncRun
from app.support.store import support_data_store
from app.support.types import (
    NormalizedSupportArticle,
    NormalizedSupportComment,
    NormalizedSupportCustomer,
    NormalizedSupportTicket,
)

DEMO_PROVIDER = "zendesk"


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)


async def seed_demo_data(
    session: AsyncSession,
    *,
    tenant_id: str,
    requested_by: str,
) -> dict[str, Any]:
    """Seed an idempotent demo corpus that exercises tickets, comments, and articles."""
    tickets = _demo_tickets()
    comments = _demo_comments()
    articles = _demo_articles()

    ticket_created = 0
    comment_created = 0
    article_created = 0
    customers_created = 0

    for ticket in tickets:
        if ticket.customer:
            customers_created += int(
                await support_data_store.upsert_customer(
                    session,
                    tenant_id=tenant_id,
                    customer=ticket.customer,
                )
            )
        ticket_created += int(
            await support_data_store.upsert_ticket(
                session,
                tenant_id=tenant_id,
                ticket=ticket,
            )
        )

    for comment in comments:
        comment_created += int(
            await support_data_store.upsert_comment(
                session,
                tenant_id=tenant_id,
                comment=comment,
            )
        )

    for article in articles:
        article_created += int(
            await support_data_store.upsert_article(
                session,
                tenant_id=tenant_id,
                article=article,
            )
        )

    run = SupportSyncRun(
        tenant_id=tenant_id,
        provider=DEMO_PROVIDER,
        status="succeeded",
        records_seen=len(tickets),
        records_upserted=len(tickets),
        records_skipped=0,
        cursor_finished_at="2026-05-30T15:20:00Z",
        metadata_={
            "demo": True,
            "customers_created": customers_created,
            "tickets_created": ticket_created,
            "comments_seen": len(comments),
            "comments_upserted": len(comments),
            "comments_created": comment_created,
            "articles_seen": len(articles),
            "articles_upserted": len(articles),
            "articles_created": article_created,
        },
        started_at=datetime.utcnow(),
        finished_at=datetime.utcnow(),
        created_by=requested_by,
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)

    return {
        "provider": DEMO_PROVIDER,
        "sync_run_id": run.id,
        "customers_created": customers_created,
        "tickets_seen": len(tickets),
        "tickets_created": ticket_created,
        "comments_seen": len(comments),
        "comments_created": comment_created,
        "articles_seen": len(articles),
        "articles_created": article_created,
    }


def _demo_tickets() -> list[NormalizedSupportTicket]:
    return [
        NormalizedSupportTicket(
            provider=DEMO_PROVIDER,
            external_id="demo-ticket-export-timeout",
            subject="CSV export times out after 30 seconds",
            description=(
                "Customer cannot export a 50k-row CSV report. The request reaches 30 seconds, "
                "then the browser shows a timeout even though smaller exports succeed."
            ),
            status="solved",
            priority="high",
            category="incident",
            channel="web",
            requester_external_id="demo-customer-ops-lead",
            assignee_external_id="demo-agent-maya",
            organization_external_id="demo-org-acme",
            tags=["export", "timeout", "csv", "worker"],
            source_url="https://example.zendesk.com/agent/tickets/demo-ticket-export-timeout",
            created_at_external=_dt("2026-05-28T10:00:00Z"),
            updated_at_external=_dt("2026-05-28T12:30:00Z"),
            raw={"id": "demo-ticket-export-timeout", "demo": True},
            customer=NormalizedSupportCustomer(
                provider=DEMO_PROVIDER,
                external_id="demo-customer-ops-lead",
                email="ops-lead@example.com",
                name="Ops Lead",
                role="admin",
                raw={"demo": True},
            ),
        ),
        NormalizedSupportTicket(
            provider=DEMO_PROVIDER,
            external_id="demo-ticket-export-timeout-repeat",
            subject="Weekly CSV export hits gateway timeout again",
            description=(
                "A second customer report export fails at the gateway timeout. The dataset is large "
                "and the account is still routed through the synchronous export path."
            ),
            status="solved",
            priority="high",
            category="incident",
            channel="email",
            requester_external_id="demo-customer-ops-lead",
            assignee_external_id="demo-agent-maya",
            organization_external_id="demo-org-acme",
            tags=["export", "timeout", "csv", "async"],
            source_url="https://example.zendesk.com/agent/tickets/demo-ticket-export-timeout-repeat",
            created_at_external=_dt("2026-05-29T13:15:00Z"),
            updated_at_external=_dt("2026-05-29T15:00:00Z"),
            raw={"id": "demo-ticket-export-timeout-repeat", "demo": True},
            customer=NormalizedSupportCustomer(
                provider=DEMO_PROVIDER,
                external_id="demo-customer-ops-lead",
                email="ops-lead@example.com",
                name="Ops Lead",
                role="admin",
                raw={"demo": True},
            ),
        ),
        NormalizedSupportTicket(
            provider=DEMO_PROVIDER,
            external_id="demo-ticket-export-timeout-open",
            subject="Report export endpoint returns timeout for 80k rows",
            description=(
                "New inbound ticket: the customer is seeing the same 30 second timeout pattern on "
                "large report exports and needs an agent response before their executive review."
            ),
            status="open",
            priority="high",
            category="incident",
            channel="web",
            requester_external_id="demo-customer-eng",
            assignee_external_id=None,
            organization_external_id="demo-org-beta",
            tags=["export", "timeout", "reports", "csv"],
            source_url="https://example.zendesk.com/agent/tickets/demo-ticket-export-timeout-open",
            created_at_external=_dt("2026-05-31T09:10:00Z"),
            updated_at_external=_dt("2026-05-31T09:25:00Z"),
            raw={"id": "demo-ticket-export-timeout-open", "demo": True},
            customer=NormalizedSupportCustomer(
                provider=DEMO_PROVIDER,
                external_id="demo-customer-eng",
                email="eng@example.com",
                name="Engineering Manager",
                role="admin",
                raw={"demo": True},
            ),
        ),
        NormalizedSupportTicket(
            provider=DEMO_PROVIDER,
            external_id="demo-ticket-billing-plan",
            subject="Billing plan changed but invoice still shows old seat count",
            description=(
                "Customer downgraded seats before renewal, but the invoice preview still shows the "
                "previous seat count. They need confirmation before finance approval."
            ),
            status="solved",
            priority="medium",
            category="question",
            channel="email",
            requester_external_id="demo-customer-finance",
            assignee_external_id="demo-agent-lee",
            organization_external_id="demo-org-acme",
            tags=["billing", "invoice", "seat-count"],
            source_url="https://example.zendesk.com/agent/tickets/demo-ticket-billing-plan",
            created_at_external=_dt("2026-05-29T09:15:00Z"),
            updated_at_external=_dt("2026-05-29T10:20:00Z"),
            raw={"id": "demo-ticket-billing-plan", "demo": True},
            customer=NormalizedSupportCustomer(
                provider=DEMO_PROVIDER,
                external_id="demo-customer-finance",
                email="finance@example.com",
                name="Finance Buyer",
                role="billing_admin",
                raw={"demo": True},
            ),
        ),
        NormalizedSupportTicket(
            provider=DEMO_PROVIDER,
            external_id="demo-ticket-billing-cache-repeat",
            subject="Invoice preview stale after seat downgrade",
            description=(
                "Customer reduced seats before renewal, but the invoice preview still reflects the "
                "old quantity. They ask if finance can approve the corrected amount."
            ),
            status="solved",
            priority="medium",
            category="question",
            channel="email",
            requester_external_id="demo-customer-finance",
            assignee_external_id="demo-agent-lee",
            organization_external_id="demo-org-acme",
            tags=["billing", "invoice", "cache"],
            source_url="https://example.zendesk.com/agent/tickets/demo-ticket-billing-cache-repeat",
            created_at_external=_dt("2026-05-30T11:45:00Z"),
            updated_at_external=_dt("2026-05-30T12:15:00Z"),
            raw={"id": "demo-ticket-billing-cache-repeat", "demo": True},
            customer=NormalizedSupportCustomer(
                provider=DEMO_PROVIDER,
                external_id="demo-customer-finance",
                email="finance@example.com",
                name="Finance Buyer",
                role="billing_admin",
                raw={"demo": True},
            ),
        ),
        NormalizedSupportTicket(
            provider=DEMO_PROVIDER,
            external_id="demo-ticket-slack-alerts",
            subject="Slack alerts stopped after channel rename",
            description=(
                "Customer renamed their incident-alerts Slack channel. Alerts stopped because the "
                "stored channel id no longer matched the integration mapping."
            ),
            status="solved",
            priority="medium",
            category="incident",
            channel="chat",
            requester_external_id="demo-customer-eng",
            assignee_external_id="demo-agent-ari",
            organization_external_id="demo-org-beta",
            tags=["slack", "alerts", "integration"],
            source_url="https://example.zendesk.com/agent/tickets/demo-ticket-slack-alerts",
            created_at_external=_dt("2026-05-30T14:00:00Z"),
            updated_at_external=_dt("2026-05-30T15:20:00Z"),
            raw={"id": "demo-ticket-slack-alerts", "demo": True},
            customer=NormalizedSupportCustomer(
                provider=DEMO_PROVIDER,
                external_id="demo-customer-eng",
                email="eng@example.com",
                name="Engineering Manager",
                role="admin",
                raw={"demo": True},
            ),
        ),
    ]


def _demo_comments() -> list[NormalizedSupportComment]:
    return [
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-export-timeout",
            external_id="demo-comment-export-1",
            author_external_id="demo-agent-maya",
            body_text=(
                "We confirmed the export worker was healthy but the request path was using the "
                "synchronous CSV endpoint. Switching the account to async export and asking the "
                "customer to retry generated the file successfully in 3 minutes."
            ),
            body_html=None,
            is_public=False,
            created_at_external=_dt("2026-05-28T11:00:00Z"),
            raw={"id": "demo-comment-export-1", "demo": True},
        ),
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-export-timeout",
            external_id="demo-comment-export-2",
            author_external_id="demo-agent-maya",
            body_text=(
                "Customer-facing reply: Large CSV exports now run asynchronously. Please retry from "
                "Reports > Exports; you will receive an email with the download link when the file is ready."
            ),
            body_html=None,
            is_public=True,
            created_at_external=_dt("2026-05-28T12:00:00Z"),
            raw={"id": "demo-comment-export-2", "demo": True},
        ),
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-export-timeout-repeat",
            external_id="demo-comment-export-repeat-1",
            author_external_id="demo-agent-maya",
            body_text=(
                "Repeated pattern confirmed. Enabled async CSV generation, invalidated the old export "
                "route cache, and reused the customer-facing async export response."
            ),
            body_html=None,
            is_public=False,
            created_at_external=_dt("2026-05-29T14:20:00Z"),
            raw={"id": "demo-comment-export-repeat-1", "demo": True},
        ),
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-export-timeout-open",
            external_id="demo-comment-export-open-1",
            author_external_id="demo-agent-maya",
            body_text=(
                "Triage note: Similar to prior async CSV export timeout cases. Check whether the "
                "customer is still on the synchronous endpoint before escalating."
            ),
            body_html=None,
            is_public=False,
            created_at_external=_dt("2026-05-31T09:30:00Z"),
            raw={"id": "demo-comment-export-open-1", "demo": True},
        ),
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-billing-plan",
            external_id="demo-comment-billing-1",
            author_external_id="demo-agent-lee",
            body_text=(
                "Billing cache refresh fixed the invoice preview. The subscription had the correct seat "
                "count; only the preview cache was stale."
            ),
            body_html=None,
            is_public=False,
            created_at_external=_dt("2026-05-29T09:45:00Z"),
            raw={"id": "demo-comment-billing-1", "demo": True},
        ),
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-billing-cache-repeat",
            external_id="demo-comment-billing-repeat-1",
            author_external_id="demo-agent-lee",
            body_text=(
                "Resolution: Refreshed the billing preview cache, verified the subscription source of "
                "truth, and sent finance the corrected invoice preview."
            ),
            body_html=None,
            is_public=True,
            created_at_external=_dt("2026-05-30T12:05:00Z"),
            raw={"id": "demo-comment-billing-repeat-1", "demo": True},
        ),
        NormalizedSupportComment(
            provider=DEMO_PROVIDER,
            ticket_external_id="demo-ticket-slack-alerts",
            external_id="demo-comment-slack-1",
            author_external_id="demo-agent-ari",
            body_text=(
                "Resolution: Re-authorized Slack, selected the renamed #incident-alerts channel, and "
                "sent a test alert. Alerts resumed immediately."
            ),
            body_html=None,
            is_public=True,
            created_at_external=_dt("2026-05-30T15:05:00Z"),
            raw={"id": "demo-comment-slack-1", "demo": True},
        ),
    ]


def _demo_articles() -> list[NormalizedSupportArticle]:
    return [
        NormalizedSupportArticle(
            provider=DEMO_PROVIDER,
            external_id="demo-article-async-exports",
            title="Large exports should use async CSV generation",
            body_text=(
                "For exports larger than 10k rows, enable async export. The synchronous endpoint may "
                "time out after 30 seconds. Async export emails a secure download link once complete."
            ),
            body_html=None,
            locale="en-us",
            source_url="https://example.zendesk.com/hc/articles/demo-article-async-exports",
            updated_at_external=_dt("2026-05-28T08:00:00Z"),
            raw={"id": "demo-article-async-exports", "demo": True},
        ),
        NormalizedSupportArticle(
            provider=DEMO_PROVIDER,
            external_id="demo-article-billing-cache",
            title="Refresh billing preview cache after plan changes",
            body_text=(
                "If invoice preview shows stale seats after a plan change, refresh the billing preview "
                "cache and verify the subscription source of truth before escalating."
            ),
            body_html=None,
            locale="en-us",
            source_url="https://example.zendesk.com/hc/articles/demo-article-billing-cache",
            updated_at_external=_dt("2026-05-29T08:00:00Z"),
            raw={"id": "demo-article-billing-cache", "demo": True},
        ),
        NormalizedSupportArticle(
            provider=DEMO_PROVIDER,
            external_id="demo-article-slack-channel-renames",
            title="Slack channel renames require integration remapping",
            body_text=(
                "When a Slack channel is renamed or recreated, re-authorize Slack and select the target "
                "channel again. Send a test alert before closing the support ticket."
            ),
            body_html=None,
            locale="en-us",
            source_url="https://example.zendesk.com/hc/articles/demo-article-slack-channel-renames",
            updated_at_external=_dt("2026-05-30T08:00:00Z"),
            raw={"id": "demo-article-slack-channel-renames", "demo": True},
        ),
    ]
