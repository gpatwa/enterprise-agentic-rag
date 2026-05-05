# services/api/app/clients/qdrant.py
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

from app.config import settings

DEFAULT_TENANT_ID = "default"


class VectorDBClient:
    """
    Async Client for Qdrant.
    All search operations are filtered by tenant_id for data isolation.
    """
    def __init__(self):
        # Use gRPC in prod (port 6334), REST locally (port 6333)
        use_grpc = settings.ENV != "dev"
        self.client = AsyncQdrantClient(
            host=settings.QDRANT_HOST,
            port=settings.QDRANT_PORT,
            prefer_grpc=use_grpc
        )

    async def search(
        self,
        vector: list[float],
        limit: int = 5,
        tenant_id: str = DEFAULT_TENANT_ID,
    ):
        """
        Performs Semantic Search, filtered by tenant_id.

        Qdrant's payload filtering ensures that tenant-A's data
        is never returned for tenant-B's queries.
        """
        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="tenant_id",
                    match=models.MatchValue(value=tenant_id),
                )
            ]
        )

        return await self.client.search(
            collection_name=settings.QDRANT_COLLECTION,
            query_vector=vector,
            query_filter=query_filter,
            limit=limit,
            with_payload=True
        )

# Global instance
qdrant_client = VectorDBClient()
