# services/api/app/clients/reranker/cross_encoder_reranker.py
"""
Cross-encoder re-ranker — calls a dedicated Ray Serve endpoint.

The endpoint accepts a batch of (query, document) pairs and returns
relevance scores. Much more accurate than LLM scoring, with ~50ms latency.

Used when RERANKER_PROVIDER=cross_encoder (recommended for production).

Expected endpoint API:
  POST /rerank
  {
    "query": "Who founded Acme?",
    "documents": ["doc1 text", "doc2 text", ...],
    "top_k": 8
  }
  → {"results": [{"index": 0, "score": 0.95}, {"index": 2, "score": 0.82}, ...]}
"""
import logging
from typing import Optional

import httpx

from app.clients.reranker.base import ScoredDocument
from app.config import settings

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Cross-encoder re-ranker backed by a Ray Serve endpoint.

    The endpoint runs a model like cross-encoder/ms-marco-MiniLM-L-12-v2
    and returns calibrated relevance scores.
    """

    def __init__(
        self,
        endpoint: str = "",
        score_threshold: float = 0.3,
    ):
        self.endpoint = endpoint or settings.RERANKER_ENDPOINT
        self.score_threshold = score_threshold
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        limits = httpx.Limits(max_keepalive_connections=10, max_connections=30)
        self.client = httpx.AsyncClient(timeout=30.0, limits=limits)
        logger.info(
            f"CrossEncoderReranker initialized "
            f"(endpoint={self.endpoint}, threshold={self.score_threshold})"
        )

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()

    async def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = 8,
    ) -> list[ScoredDocument]:
        """Re-rank via cross-encoder endpoint."""
        if not documents:
            return []

        if not self.client:
            raise RuntimeError(
                "CrossEncoderReranker not initialized. Call start() first."
            )

        try:
            resp = await self.client.post(
                self.endpoint,
                json={
                    "query": query,
                    "documents": documents,
                    "top_k": top_k,
                },
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            scored = []
            for item in results:
                idx = item["index"]
                score = float(item["score"])
                if idx < len(documents):
                    scored.append(
                        ScoredDocument(
                            text=documents[idx],
                            score=score,
                            original_rank=idx,
                        )
                    )

            # Sort by score descending
            scored.sort(key=lambda d: d.score, reverse=True)

            # Filter by threshold, always keep at least 1
            filtered = [d for d in scored if d.score >= self.score_threshold]
            if not filtered and scored:
                filtered = [scored[0]]

            return filtered[:top_k]

        except Exception as e:
            logger.warning(
                f"Cross-encoder reranking failed ({e}), using original order"
            )
            return [
                ScoredDocument(text=doc, score=1.0, original_rank=i)
                for i, doc in enumerate(documents[:top_k])
            ]
