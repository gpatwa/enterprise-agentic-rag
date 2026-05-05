# services/api/app/routes/feedback.py
"""
In-app feedback endpoint.

Stakeholders click "Send feedback" anywhere in the app → POST here →
we forward to a Slack incoming webhook. Audit-logged so we have a
durable record even if the Slack message is missed.

Why backend-routed (instead of frontend → Slack directly)
---------------------------------------------------------
- Slack webhook URL stays out of the browser bundle (it's a credential)
- Authenticated user attribution comes from the JWT (you can't spoof
  who reported the bug without forging a token)
- Rate-limited per tenant (via the existing rate_limit dependency)
- Structured server-side audit trail
- Lets us swap Slack for Linear / email / DB without a frontend change

Behaviour when the webhook isn't configured
-------------------------------------------
- The endpoint still returns 200 — feedback is logged (audit + stdout)
  but not relayed to Slack. Lets local dev + alpha environments without
  a webhook still exercise the flow without surface errors.

Note: a previous incarnation of this file held a thumbs-up/down route
for AI response rating that was never wired to main.py and referenced a
non-existent `feedback` table. That is replaced wholesale here. If
response-level rating comes back, it should live in its own module
(routes/response_feedback.py) to keep concerns separated.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.audit import manager as audit_manager
from app.auth.tenant import TenantContext, get_tenant_context
from app.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


# ── Pydantic IO ────────────────────────────────────────────────────────


class FeedbackCategory:
    BUG = "bug"
    IDEA = "idea"
    COMMENT = "comment"

    ALL = (BUG, IDEA, COMMENT)


_EMOJI = {
    FeedbackCategory.BUG: "🐛",
    FeedbackCategory.IDEA: "💡",
    FeedbackCategory.COMMENT: "💬",
}


class FeedbackRequest(BaseModel):
    """
    Body of POST /api/v1/feedback. Kept tight on purpose — alpha
    feedback should be friction-free, not a 12-field form.
    """

    message: str = Field(
        ..., min_length=1, max_length=4000,
        description="The user's free-form feedback.",
    )
    category: str = Field(
        default=FeedbackCategory.COMMENT,
        description='One of "bug", "idea", "comment".',
    )
    current_url: Optional[str] = Field(
        default=None,
        max_length=1000,
        description="Page URL the user was on when they hit Send.",
    )
    user_agent: Optional[str] = Field(default=None, max_length=500)


class FeedbackResponse(BaseModel):
    ok: bool
    relayed_to_slack: bool


# ── Route ──────────────────────────────────────────────────────────────


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    body: FeedbackRequest,
    ctx: TenantContext = Depends(get_tenant_context),
) -> FeedbackResponse:
    """
    Capture an in-app feedback submission.

    Validates the category, attributes to the authenticated user,
    audit-logs the submission, and best-effort relays to Slack. Never
    raises on relay failure — alpha shouldn't surface infra issues to
    stakeholders giving feedback.
    """
    if body.category not in FeedbackCategory.ALL:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "feedback.invalid_category",
                "message": (
                    f"category must be one of {FeedbackCategory.ALL}; "
                    f"got {body.category!r}"
                ),
            },
        )

    relayed = await _relay_to_slack(ctx, body)

    # Audit ALWAYS fires, even if Slack relay failed. The audit log is the
    # durable journal; Slack is convenience.
    await audit_manager.log_event(
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        role=ctx.role,
        event_type="feedback.submitted",
        method="POST",
        path="/api/v1/feedback",
        status_code=200,
        payload_summary=body.message[:500],
        extra={
            "category": body.category,
            "current_url": body.current_url,
            "relayed_to_slack": relayed,
            "message_length": len(body.message),
        },
    )

    return FeedbackResponse(ok=True, relayed_to_slack=relayed)


# ── Slack relay ────────────────────────────────────────────────────────


async def _relay_to_slack(ctx: TenantContext, body: FeedbackRequest) -> bool:
    """
    Best-effort POST to a Slack incoming webhook. Returns True on success,
    False on any failure (missing webhook, network error, non-2xx response).
    """
    webhook_url = getattr(settings, "FEEDBACK_SLACK_WEBHOOK_URL", None)
    if not webhook_url:
        logger.info(
            "feedback received (no slack webhook configured): "
            "tenant=%s user=%s category=%s",
            ctx.tenant_id, ctx.user_id, body.category,
        )
        return False

    payload = _build_slack_payload(ctx, body)
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.post(webhook_url, json=payload)
        if res.status_code >= 300:
            logger.warning(
                "slack webhook returned %s: %s",
                res.status_code, res.text[:200],
            )
            return False
        return True
    except (httpx.HTTPError, asyncio.TimeoutError) as e:
        # Pure network failure — still audit, just don't tell the user.
        logger.warning("slack webhook failed: %s", e)
        return False
    except Exception as e:  # pragma: no cover — defensive
        logger.error("slack webhook crashed: %s", e, exc_info=True)
        return False


def _build_slack_payload(ctx: TenantContext, body: FeedbackRequest) -> dict:
    """
    Format as Slack Block Kit so the message has a useful structure
    rather than a wall of text. Matches Slack's webhook contract.
    """
    emoji = _EMOJI.get(body.category, "💬")
    header_text = (
        f"{emoji} {body.category.capitalize()} from "
        f"{ctx.user_id} (tenant={ctx.tenant_id}, role={ctx.role})"
    )
    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": header_text[:150]},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                # Slack truncates >3000 chars per text block; we already
                # cap the message at 4000 chars upstream.
                "text": _slack_clean(body.message)[:2900],
            },
        },
    ]
    context_elements: list[dict] = []
    if body.current_url:
        context_elements.append(
            {
                "type": "mrkdwn",
                "text": f"<{body.current_url}|↗ open page>",
            }
        )
    context_elements.append(
        {
            "type": "mrkdwn",
            "text": (
                f"_user_: `{ctx.user_id}`  ·  "
                f"_tenant_: `{ctx.tenant_id}`  ·  "
                f"_role_: `{ctx.role}`"
            ),
        }
    )
    blocks.append({"type": "context", "elements": context_elements})

    return {
        "text": header_text,  # fallback for notifications/email digests
        "blocks": blocks,
    }


def _slack_clean(text: str) -> str:
    """
    Minimal Slack-mrkdwn safety. Stop user-supplied text from being
    rendered as a channel-wide @-mention.
    """
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("@channel", "@​channel")
        .replace("@here", "@​here")
        .replace("@everyone", "@​everyone")
    )


__all__ = [
    "router",
    "FeedbackCategory",
    "FeedbackRequest",
    "FeedbackResponse",
    "_build_slack_payload",
    "_relay_to_slack",
]
