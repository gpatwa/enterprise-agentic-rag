# services/api/app/context/layer3_code.py
"""
Layer 3: Code & Pipeline Context.

Fetches relevant code/pipeline context, ETL descriptions, SQL queries,
and data lineage information that matches the user's query.
"""
import logging
from typing import List

from sqlalchemy import and_, or_, select

import app.memory.postgres as _pg
from app.config import settings
from app.context.models import CodeContext

logger = logging.getLogger(__name__)

_single_tenant = settings.SINGLE_TENANT_MODE


class CodeContextLayer:
    """Fetch code context, pipeline descriptions, and data lineage."""

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
                    conditions.append(CodeContext.tenant_id == tenant_id)

                # Match query terms against name and description
                query_lower = query.lower()
                words = [w for w in query_lower.split() if len(w) >= 3]
                if not words:
                    return ""

                term_conditions = []
                for word in words[:5]:  # Limit to 5 terms to avoid huge queries
                    term_conditions.append(CodeContext.name.ilike(f"%{word}%"))
                    term_conditions.append(CodeContext.description.ilike(f"%{word}%"))

                conditions.append(or_(*term_conditions))

                result = await session.execute(
                    select(CodeContext)
                    .where(and_(*conditions))
                    .limit(5)
                )
                contexts = result.scalars().all()

                if not contexts:
                    return ""

                lines = []
                type_icons = {
                    "etl_pipeline": "🔧",
                    "sql_query": "🗄️",
                    "api_endpoint": "🌐",
                    "data_lineage": "🔗",
                }
                for ctx in contexts:
                    icon = type_icons.get(ctx.context_type, "💻")
                    line = f"{icon} {ctx.name} ({ctx.context_type}): {ctx.description}"
                    if ctx.lineage:
                        upstream = ctx.lineage.get("upstream", [])
                        downstream = ctx.lineage.get("downstream", [])
                        if upstream:
                            line += f" | Upstream: {', '.join(upstream)}"
                        if downstream:
                            line += f" | Downstream: {', '.join(downstream)}"
                    lines.append(line)

                return "\n".join(lines)

        except Exception as e:
            logger.error(f"Layer 3 (code context) fetch failed: {e}")
            return ""
