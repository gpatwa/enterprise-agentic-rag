# services/api/app/clients/reranker/null_client.py
"""
No-op re-ranker — passes documents through in their original order.
Used when RERANKER_PROVIDER=none (default for local dev).
"""
import logging

from app.clients.reranker.base import ScoredDocument

logger = logging.getLogger(__name__)


class NullReranker:
    """Pass-through reranker that preserves original retrieval order."""

    async def start(self) -> None:
        logger.info("NullReranker initialized (pass-through, no re-scoring)")

    async def close(self) -> None:
        pass

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 8,
    ) -> list[ScoredDocument]:
        """Return documents in original order with score=1.0."""
        return [
            ScoredDocument(text=doc, score=1.0, original_rank=i)
            for i, doc in enumerate(documents[:top_k])
        ]
