# services/api/app/routes/home.py
"""
Home landing endpoint — bundle for the Compass Home page in a single
request to minimize round-trips on first paint.

This composes from existing managers/probes:
  - threads.manager.list_threads + list_saved_questions(pinned_only=True)
  - sources health probes (best-effort, with timeouts)
  - context_layer counts (live SQLAlchemy)
  - quick-start categories — static for now; admin-editable in W3
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends

from app.auth.tenant import TenantContext, get_tenant_context
from app.config import settings
from app.routes.sources import (
    _probe_neo4j,
    _probe_postgres,
    _probe_qdrant,
    _with_timeout,
    PROBE_TIMEOUT_SECONDS,
)
from app.threads import manager as threads_manager

router = APIRouter()


def _now() -> datetime:
    return datetime.utcnow()


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


# ── Static / admin-editable content ──────────────────────────────────

QUICK_START_CATEGORIES = [
    {
        "id": "revenue",
        "icon": "trending-up",
        "title": "Revenue trends",
        "description": "Monthly · YoY · by category",
        "questions": [
            {"id": "qr_1", "text": "What was revenue by month?"},
            {"id": "qr_2", "text": "Top 10 categories by revenue"},
            {"id": "qr_3", "text": "YoY growth by quarter"},
        ],
    },
    {
        "id": "products",
        "icon": "shopping-bag",
        "title": "Top products",
        "description": "Categories · sellers · items",
        "questions": [
            {"id": "qp_1", "text": "Top 10 categories by revenue"},
            {"id": "qp_2", "text": "Top sellers Q1"},
            {"id": "qp_3", "text": "Slow movers last 90 days"},
        ],
    },
    {
        "id": "reviews",
        "icon": "star",
        "title": "Reviews & ratings",
        "description": "Scores · sentiment · regions",
        "questions": [
            {"id": "qrv_1", "text": "Average review by state"},
            {"id": "qrv_2", "text": "Review score distribution"},
            {"id": "qrv_3", "text": "Categories with the most negative reviews"},
        ],
    },
    {
        "id": "delivery",
        "icon": "truck",
        "title": "Delivery insights",
        "description": "Times · lateness · regions",
        "questions": [
            {"id": "qd_1", "text": "Avg delivery time by month"},
            {"id": "qd_2", "text": "Late delivery rate by state"},
            {"id": "qd_3", "text": "Carrier performance comparison"},
        ],
    },
]


# ── Endpoint ─────────────────────────────────────────────────────────


@router.get("/landing")
async def get_landing(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """
    Bundle: user · tenant · pinned · recent threads · quick-start ·
    sources · knowledge counts · governance.

    All slow operations run in parallel.
    """
    pinned_task = threads_manager.list_saved_questions(
        ctx.tenant_id, ctx.user_id, pinned_only=True, limit=10
    )
    recent_task = threads_manager.list_threads(ctx.tenant_id, ctx.user_id, limit=10)
    knowledge_task = _count_knowledge_layers(ctx.tenant_id)

    pg_task = _with_timeout(
        _probe_postgres(), PROBE_TIMEOUT_SECONDS, {"type": "postgres", "name": "PostgreSQL"}
    )
    qd_task = _with_timeout(
        _probe_qdrant(), PROBE_TIMEOUT_SECONDS, {"type": "qdrant", "name": "Qdrant Vector"}
    )
    neo_task = _with_timeout(
        _probe_neo4j(), PROBE_TIMEOUT_SECONDS, {"type": "neo4j", "name": "Neo4j Graph"}
    )

    pinned, recent, knowledge_counts, pg, qd, neo = await asyncio.gather(
        pinned_task,
        recent_task,
        knowledge_task,
        pg_task,
        qd_task,
        neo_task,
    )

    # Translate saved-question rows into pinned-question shape expected by FE.
    pinned_for_fe = [
        {
            "id": p["id"],
            "title": p["title"],
            "last_run_at": p["last_run_at"],
            "last_result_preview": p["last_result_preview"],
        }
        for p in pinned
    ]

    return {
        "user": {
            "id": ctx.user_id,
            "name": ctx.user_id.split("@")[0].title() if "@" in ctx.user_id else ctx.user_id.title(),
            "role": ctx.role,
        },
        "tenant": {
            "id": ctx.tenant_id,
            "name": ctx.tenant_id.replace("-", " ").title(),
            "residency": settings.AWS_REGION or "us-east-1",
        },
        "pinned_questions": pinned_for_fe,
        "recent_threads": recent,
        "quick_start_categories": QUICK_START_CATEGORIES,
        "sources": [pg, qd, neo, {"type": "slack", "name": "Slack export", "status": "not_connected"}],
        "knowledge_counts": knowledge_counts,
        "governance": {
            "pii_redaction": True,
            "audit_logging": True,
        },
    }


async def _count_knowledge_layers(tenant_id: str) -> dict[str, int]:
    """Count entries in each knowledge-layer table for the tenant."""
    if not settings.CONTEXT_LAYERS_ENABLED:
        return {"glossary": 0, "business_rules": 0, "code_context": 0}

    try:
        import app.memory.postgres as _pg
        from sqlalchemy import func, select

        if _pg.AsyncSessionLocal is None:
            return {"glossary": 0, "business_rules": 0, "code_context": 0}

        from app.context.models import Annotation, BusinessContext, CodeContext

        async with _pg.AsyncSessionLocal() as session:
            glossary = await session.scalar(
                select(func.count())
                .select_from(Annotation)
                .where(Annotation.tenant_id == tenant_id, Annotation.annotation_type == "glossary")
            )
            rules = await session.scalar(
                select(func.count())
                .select_from(BusinessContext)
                .where(BusinessContext.tenant_id == tenant_id)
            )
            code = await session.scalar(
                select(func.count())
                .select_from(CodeContext)
                .where(CodeContext.tenant_id == tenant_id)
            )

        return {
            "glossary": glossary or 0,
            "business_rules": rules or 0,
            "code_context": code or 0,
        }
    except Exception:
        return {"glossary": 0, "business_rules": 0, "code_context": 0}
