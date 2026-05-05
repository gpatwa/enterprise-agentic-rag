# services/api/app/clients/vectordb/qdrant_impl.py
"""
Qdrant implementation of the VectorDBClient protocol.
Wraps the AsyncQdrantClient with a provider-agnostic interface.
"""
import logging
import uuid

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)


class QdrantVectorClient:
    """
    Qdrant-backed VectorDBClient.

    Translates generic filter dicts into Qdrant FieldCondition filters,
    and normalises search results into plain dicts.
    """

    def __init__(self, host: str, port: int, prefer_grpc: bool = False):
        self._host = host
        self._port = port
        self._prefer_grpc = prefer_grpc
        self.client: AsyncQdrantClient | None = None

    async def connect(self) -> None:
        if not self.client:
            self.client = AsyncQdrantClient(
                host=self._host,
                port=self._port,
                prefer_grpc=self._prefer_grpc,
            )
            logger.info(
                f"QdrantVectorClient connected to {self._host}:{self._port}"
            )

    async def close(self) -> None:
        if self.client:
            await self.client.close()
            self.client = None

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_filter(filters: dict | None) -> models.Filter | None:
        """Convert a flat dict of key-value pairs into a Qdrant Filter."""
        if not filters:
            return None
        conditions = [
            models.FieldCondition(
                key=k,
                match=models.MatchValue(value=v),
            )
            for k, v in filters.items()
        ]
        return models.Filter(must=conditions)

    @staticmethod
    def _normalise_result(point) -> dict:
        """Convert a Qdrant ScoredPoint into a plain dict."""
        return {
            "id": str(point.id),
            "score": point.score,
            "payload": point.payload or {},
        }

    # ------------------------------------------------------------------
    # protocol methods
    # ------------------------------------------------------------------

    async def search(
        self,
        collection: str,
        vector: list[float],
        limit: int = 5,
        filters: dict | None = None,
        score_threshold: float | None = None,
    ) -> list[dict]:
        kwargs: dict = dict(
            collection_name=collection,
            query_vector=vector,
            limit=limit,
            with_payload=True,
        )
        qf = self._build_filter(filters)
        if qf:
            kwargs["query_filter"] = qf
        if score_threshold is not None:
            kwargs["score_threshold"] = score_threshold

        results = await self.client.search(**kwargs)
        return [self._normalise_result(r) for r in results]

    async def upsert(
        self,
        collection: str,
        points: list[dict],
    ) -> None:
        qdrant_points = [
            models.PointStruct(
                id=p.get("id", str(uuid.uuid4())),
                vector=p["vector"],
                payload=p.get("payload", {}),
            )
            for p in points
        ]
        await self.client.upsert(
            collection_name=collection, points=qdrant_points
        )

    async def create_collection(
        self,
        collection: str,
        vector_size: int,
    ) -> None:
        collections = await self.client.get_collections()
        existing = [c.name for c in collections.collections]
        if collection not in existing:
            await self.client.create_collection(
                collection_name=collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            logger.info(f"Created Qdrant collection: {collection}")

    async def delete_by_filter(
        self,
        collection: str,
        filters: dict,
    ) -> None:
        qf = self._build_filter(filters)
        if qf:
            await self.client.delete(
                collection_name=collection,
                points_selector=models.FilterSelector(filter=qf),
            )
