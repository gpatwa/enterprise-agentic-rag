# services/api/app/routes/documents.py
"""
Lists ingested documents by querying distinct filenames from the vector DB.
Used by the Chat UI header to show what data is available for querying.
"""
import logging

from fastapi import APIRouter, Depends

from app.auth.tenant import TenantContext, get_tenant_context
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/list")
async def list_documents(ctx: TenantContext = Depends(get_tenant_context)):
    """
    Return distinct ingested filenames and chunk counts for the current tenant.
    Queries the vector DB (Qdrant) payload metadata.
    """
    try:
        from qdrant_client.http.models import FieldCondition, Filter, MatchValue

        from app.clients.qdrant import qdrant_client

        tenant_filter = Filter(
            must=[FieldCondition(key="tenant_id", match=MatchValue(value=ctx.tenant_id))]
        )

        # Scroll through points to collect distinct filenames
        file_counts: dict[str, int] = {}
        offset = None

        while True:
            results, next_offset = await qdrant_client.client.scroll(
                collection_name=settings.QDRANT_COLLECTION,
                scroll_filter=tenant_filter,
                limit=250,
                offset=offset,
                with_payload=["filename", "metadata"],
                with_vectors=False,
            )

            for point in results:
                payload = point.payload or {}
                name = (
                    payload.get("filename")
                    or payload.get("metadata", {}).get("filename")
                )
                if name:
                    file_counts[name] = file_counts.get(name, 0) + 1

            if next_offset is None:
                break
            offset = next_offset

        files = [
            {"filename": name, "chunks": count}
            for name, count in sorted(file_counts.items())
        ]

        return {"tenant_id": ctx.tenant_id, "total_files": len(files), "files": files}

    except Exception as e:
        logger.warning(f"Could not list documents: {e}")
        return {"tenant_id": ctx.tenant_id, "total_files": 0, "files": [], "error": str(e)}
