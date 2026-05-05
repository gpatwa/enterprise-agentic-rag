# services/api/app/context/layer4_business.py
"""
Layer 4: Institutional / Business Context.

Fetches business rules, organizational terminology, and role-specific
context that helps the LLM understand domain-specific meaning.
Filtered by user role at query time.
"""
import logging
from typing import List

from sqlalchemy import and_, or_, select

import app.memory.postgres as _pg
from app.config import settings
from app.context.models import BusinessContext

logger = logging.getLogger(__name__)

_single_tenant = settings.SINGLE_TENANT_MODE


class BusinessContextLayer:
    """Fetch business rules, terminology, and org-specific context."""

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
                conditions = []
                if not _single_tenant:
                    conditions.append(BusinessContext.tenant_id == tenant_id)

                # Match query terms against key and value
                query_lower = query.lower()
                words = [w for w in query_lower.split() if len(w) >= 3]
                if not words:
                    return ""

                term_conditions = [
                    BusinessContext.key.ilike(f"%{word}%")
                    for word in words[:5]
                ]
                conditions.append(or_(*term_conditions))

                result = await session.execute(
                    select(BusinessContext)
                    .where(and_(*conditions))
                    .order_by(BusinessContext.priority.desc())
                    .limit(10)
                )
                rules = result.scalars().all()

                if not rules:
                    return ""

                # Filter by user role
                filtered = []
                for rule in rules:
                    roles = rule.applies_to_roles or ["all"]
                    if "all" in roles or user_role in roles:
                        filtered.append(rule)

                if not filtered:
                    return ""

                lines = []
                type_icons = {
                    "terminology": "🏢",
                    "business_rule": "📋",
                    "role_context": "👤",
                    "org_structure": "🏗️",
                }
                for rule in filtered:
                    icon = type_icons.get(rule.context_type, "🏢")
                    lines.append(f"{icon} {rule.key}: {rule.value}")

                return "\n".join(lines)

        except Exception as e:
            logger.error(f"Layer 4 (business context) fetch failed: {e}")
            return ""
