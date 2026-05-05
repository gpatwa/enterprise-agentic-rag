# services/api/app/context/layer2_annotations.py
"""
Layer 2: Human Annotations & Glossary.

Fetches glossary definitions, KPI formulas, and document notes
that match terms in the user's query.
"""
import logging
import re
from typing import List

from sqlalchemy import and_, or_, select

import app.memory.postgres as _pg
from app.config import settings
from app.context.models import Annotation

logger = logging.getLogger(__name__)

_single_tenant = settings.SINGLE_TENANT_MODE

# Minimum word length to match against glossary keys
_MIN_TERM_LENGTH = 3


class AnnotationLayer:
    """Fetch matching glossary terms, KPI definitions, and notes."""

    async def fetch(
        self,
        query: str,
        tenant_id: str,
        filenames: List[str],
        user_role: str = "all",
    ) -> str:
        if _pg.AsyncSessionLocal is None:
            return ""

        try:
            async with _pg.AsyncSessionLocal() as session:
                # Strategy 1: Match glossary/KPI keys against query terms
                query_terms = _extract_terms(query)
                if not query_terms:
                    return ""

                conditions = []
                if not _single_tenant:
                    conditions.append(Annotation.tenant_id == tenant_id)

                # Build ILIKE conditions for each query term against the key column
                term_conditions = [
                    Annotation.key.ilike(f"%{term}%")
                    for term in query_terms
                ]
                conditions.append(or_(*term_conditions))

                result = await session.execute(
                    select(Annotation)
                    .where(and_(*conditions))
                    .order_by(Annotation.annotation_type)
                    .limit(10)
                )
                annotations = result.scalars().all()

                if not annotations:
                    return ""

                # Format by type
                lines = []
                type_icons = {
                    "glossary": "📖",
                    "kpi": "📊",
                    "description": "📝",
                    "note": "📌",
                }
                for ann in annotations:
                    icon = type_icons.get(ann.annotation_type, "📎")
                    lines.append(f"{icon} {ann.key}: {ann.value}")

                return "\n".join(lines)

        except Exception as e:
            logger.error(f"Layer 2 (annotations) fetch failed: {e}")
            return ""


def _extract_terms(query: str) -> List[str]:
    """Extract meaningful terms from query for glossary matching."""
    # Remove common stop words and short words
    stop_words = {
        "the", "is", "at", "which", "on", "a", "an", "and", "or", "but",
        "in", "with", "to", "for", "of", "are", "was", "were", "be",
        "have", "has", "had", "do", "does", "did", "will", "would",
        "could", "should", "may", "might", "can", "what", "how", "why",
        "when", "where", "who", "our", "my", "your", "their", "its",
        "this", "that", "these", "those", "from", "about", "into",
    }
    words = re.findall(r'\b\w+\b', query.lower())
    return [w for w in words if len(w) >= _MIN_TERM_LENGTH and w not in stop_words]
