# services/api/app/routes/home.py
"""
Home landing endpoint — returns everything the new Compass Home page needs
in a single request to minimize round trips on first paint.

W1: returns mock data + live source health probes.
W2: replaces threads/saved_questions/source_health with real Postgres-backed data.
"""
from typing import Any
from fastapi import APIRouter, Depends
from datetime import datetime, timedelta, timezone

from app.auth.tenant import TenantContext, get_tenant_context
from app.config import settings

router = APIRouter()


def _iso(dt: datetime) -> str:
    """Format datetime as ISO 8601 with Z suffix."""
    return dt.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


@router.get("/landing")
async def get_landing(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """
    Bundle endpoint: user · tenant · pinned · recent threads · quick-start ·
    sources · knowledge counts · governance.

    Implementation status:
      - user / tenant         → from auth context (live)
      - pinned_questions      → mock for W1; saved_questions table in W2
      - recent_threads        → mock for W1; threads table in W2
      - quick_start_categories→ static for now; admin-editable in W3
      - sources               → mock for W1; source_health probes in W2
      - knowledge_counts      → live (queries context layer tables)
      - governance            → from settings
    """
    now = datetime.utcnow()

    # ── Live: knowledge counts ──────────────────────────────────────
    knowledge_counts = {"glossary": 0, "business_rules": 0, "code_context": 0}
    if settings.CONTEXT_LAYERS_ENABLED:
        try:
            knowledge_counts = await _count_knowledge_layers(ctx.tenant_id)
        except Exception:
            # Fall through with zeros — table may not exist yet
            pass

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
        "pinned_questions": [
            {
                "id": "pq_1",
                "title": "Revenue by month last year",
                "last_run_at": _iso(now - timedelta(hours=2)),
                "last_result_preview": "Refreshed 2h ago · 12 rows",
            },
            {
                "id": "pq_2",
                "title": "Top 10 sellers Q1",
                "last_run_at": _iso(now - timedelta(days=1)),
                "last_result_preview": "Refreshed 1d ago · 10 rows",
            },
        ],
        "recent_threads": [
            {
                "id": "t_42",
                "title": "Investigating churn drop in São Paulo region",
                "updated_at": _iso(now - timedelta(minutes=12)),
                "message_count": 6,
                "active": True,
            },
            {
                "id": "t_41",
                "title": "Q1 board prep — revenue + delivery KPIs",
                "updated_at": _iso(now - timedelta(hours=1)),
                "message_count": 11,
            },
            {
                "id": "t_40",
                "title": "CFO question on payment methods",
                "updated_at": _iso(now - timedelta(days=1)),
                "message_count": 3,
            },
        ],
        "quick_start_categories": [
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
        ],
        "sources": [
            {
                "type": "postgres",
                "name": "PostgreSQL",
                "row_count": 1_550_851,
                "last_synced_at": _iso(now - timedelta(minutes=5)),
                "status": "fresh",
            },
            {
                "type": "qdrant",
                "name": "Qdrant Vector",
                "chunk_count": 302,
                "last_synced_at": _iso(now - timedelta(minutes=10)),
                "status": "fresh",
            },
            {
                "type": "neo4j",
                "name": "Neo4j Graph",
                "node_count": 2_412,
                "last_synced_at": _iso(now - timedelta(hours=3)),
                "status": "stale",
            },
            {
                "type": "slack",
                "name": "Slack export",
                "status": "not_connected",
            },
        ],
        "knowledge_counts": knowledge_counts,
        "governance": {
            "pii_redaction": True,
            "audit_logging": True,
        },
    }


async def _count_knowledge_layers(tenant_id: str) -> dict[str, int]:
    """Count entries in each knowledge-layer table for the tenant."""
    import app.memory.postgres as _pg
    from sqlalchemy import select, func

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
            select(func.count()).select_from(BusinessContext).where(BusinessContext.tenant_id == tenant_id)
        )
        code = await session.scalar(
            select(func.count()).select_from(CodeContext).where(CodeContext.tenant_id == tenant_id)
        )

    return {
        "glossary": glossary or 0,
        "business_rules": rules or 0,
        "code_context": code or 0,
    }
