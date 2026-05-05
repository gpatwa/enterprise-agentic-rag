# services/api/app/context/layer1_metadata.py
"""
Layer 1: Document Metadata & Usage Signals.

Fetches metadata for documents that appeared in retrieval results:
freshness scores, access frequency, summaries, and tags.
Also updates access tracking as a side effect.
"""
import logging
import math
from datetime import datetime
from typing import List

from sqlalchemy import and_, select, update

import app.memory.postgres as _pg
from app.config import settings
from app.context.models import DocumentMetadata

logger = logging.getLogger(__name__)

_single_tenant = settings.SINGLE_TENANT_MODE


class MetadataLayer:
    """Fetch document metadata for retrieved files and track access."""

    async def fetch(
        self,
        query: str,
        tenant_id: str,
        filenames: List[str],
        user_role: str = "all",
    ) -> str:
        if not filenames or _pg.AsyncSessionLocal is None:
            return ""

        try:
            async with _pg.AsyncSessionLocal() as session:
                conditions = [DocumentMetadata.filename.in_(filenames)]
                if not _single_tenant:
                    conditions.append(DocumentMetadata.tenant_id == tenant_id)

                result = await session.execute(
                    select(DocumentMetadata).where(and_(*conditions))
                )
                docs = result.scalars().all()

                if not docs:
                    return ""

                # Side effect: update access tracking
                doc_ids = [d.id for d in docs]
                await session.execute(
                    update(DocumentMetadata)
                    .where(DocumentMetadata.id.in_(doc_ids))
                    .values(
                        access_count=DocumentMetadata.access_count + 1,
                        last_accessed_at=datetime.utcnow(),
                    )
                )
                await session.commit()

                # Format output
                lines = []
                for doc in docs:
                    parts = [f"📄 {doc.filename}"]
                    if doc.summary:
                        parts.append(doc.summary)
                    if doc.tags:
                        parts.append(f"Tags: {', '.join(doc.tags)}")

                    freshness = _compute_freshness(doc.ingested_at)
                    parts.append(f"Freshness: {freshness:.0%}")

                    if doc.access_count and doc.access_count > 1:
                        parts.append(f"Accessed {doc.access_count} times")

                    lines.append(" | ".join(parts))

                return "\n".join(lines)

        except Exception as e:
            logger.error(f"Layer 1 (metadata) fetch failed: {e}")
            return ""


def _compute_freshness(ingested_at: datetime | None) -> float:
    """Exponential decay freshness score (1.0 = brand new, 0.0 = very old)."""
    if not ingested_at:
        return 0.5
    days_old = (datetime.utcnow() - ingested_at).days
    half_life = settings.CONTEXT_FRESHNESS_DECAY_DAYS
    return math.exp(-0.693 * days_old / half_life)  # ln(2) ≈ 0.693
