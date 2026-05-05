# services/api/app/clients/reranker/llm_reranker.py
"""
LLM-based re-ranker — uses a single LLM call to score N documents.

Sends all documents + query in one prompt, asks the LLM to return
a JSON array of relevance scores (1-10). Normalizes to 0.0-1.0.

Used when RERANKER_PROVIDER=llm (recommended for staging).
"""
import logging
from typing import Optional

import httpx

from app.clients.reranker.base import ScoredDocument
from app.config import settings

logger = logging.getLogger(__name__)

RERANK_PROMPT_TEMPLATE = """You are a relevance scoring engine. Given a query and a list of documents, score each document's relevance to the query on a scale of 1-10.

Query: {query}

Documents:
{documents_block}

Return ONLY a JSON object with a "scores" array containing exactly {n} integers (1-10), one per document in order.
Example for 3 documents: {{"scores": [8, 3, 6]}}

JSON:"""


class LLMReranker:
    """
    Single-LLM-call re-ranker.

    Sends all documents in one prompt to avoid N separate API calls.
    Falls back to original order on any error.
    """

    def __init__(self, score_threshold: float = 0.3):
        self.score_threshold = score_threshold
        self.client: Optional[httpx.AsyncClient] = None

    async def start(self) -> None:
        self.client = httpx.AsyncClient(timeout=120.0)
        logger.info(
            f"LLMReranker initialized (threshold={self.score_threshold})"
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
        """Score documents via a single LLM call, then sort & filter."""
        if not documents:
            return []

        if not self.client:
            raise RuntimeError("LLMReranker not initialized. Call start() first.")

        try:
            scores = await self._score_documents(query, documents)
            return self._apply_scores(documents, scores, top_k)
        except Exception as e:
            logger.warning(f"LLM reranking failed ({e}), using original order")
            return [
                ScoredDocument(text=doc, score=1.0, original_rank=i)
                for i, doc in enumerate(documents[:top_k])
            ]

    async def _score_documents(
        self, query: str, documents: list[str]
    ) -> list[int]:
        """Send scoring prompt to LLM, return raw 1-10 scores."""
        # Truncate each document to avoid token overflow
        truncated = [doc[:500] for doc in documents]
        documents_block = "\n".join(
            f"[Doc {i+1}]: {text}" for i, text in enumerate(truncated)
        )

        prompt = RERANK_PROMPT_TEMPLATE.format(
            query=query,
            documents_block=documents_block,
            n=len(documents),
        )

        resp = await self.client.post(
            settings.RAY_LLM_ENDPOINT,
            json={
                "model": settings.LLM_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.0,
                "max_tokens": 256,
                "stream": False,
            },
        )
        resp.raise_for_status()

        raw = resp.json()["choices"][0]["message"]["content"]

        # Parse scores using robust JSON extraction
        from app.agents.json_utils import extract_json
        result = extract_json(raw)
        scores = result.get("scores", [])

        # Validate: must have exactly N scores, all integers 1-10
        if len(scores) != len(documents):
            logger.warning(
                f"Score count mismatch: got {len(scores)}, expected {len(documents)}"
            )
            # Pad or truncate
            while len(scores) < len(documents):
                scores.append(5)  # neutral default
            scores = scores[: len(documents)]

        return [max(1, min(10, int(s))) for s in scores]

    def _apply_scores(
        self,
        documents: list[str],
        scores: list[int],
        top_k: int,
    ) -> list[ScoredDocument]:
        """Normalize scores 1-10 → 0.0-1.0, filter by threshold, sort."""
        scored = [
            ScoredDocument(
                text=doc,
                score=score / 10.0,  # Normalize: 1→0.1, 10→1.0
                original_rank=i,
            )
            for i, (doc, score) in enumerate(zip(documents, scores))
        ]

        # Sort by score descending
        scored.sort(key=lambda d: d.score, reverse=True)

        # Filter by threshold, but always keep at least 1
        filtered = [d for d in scored if d.score >= self.score_threshold]
        if not filtered:
            filtered = [scored[0]]  # Keep the best one

        return filtered[:top_k]
