# services/api/app/support/resolver.py
from __future__ import annotations

import logging
from typing import Any

from app.support.indexer import SupportIndexError, support_indexer

logger = logging.getLogger(__name__)

_llm_client = None


class SupportResolveError(RuntimeError):
    pass


def set_clients(llm) -> None:
    """Called once during app startup to inject the LLM client."""
    global _llm_client
    _llm_client = llm


class SupportResolver:
    async def resolve(
        self,
        *,
        tenant_id: str,
        question: str,
        provider: str | None = None,
        status: str | None = None,
        limit: int = 6,
    ) -> dict[str, Any]:
        query = " ".join(question.split())
        if len(query) < 2:
            raise SupportResolveError("question must be at least 2 characters")

        try:
            matches = await support_indexer.search(
                tenant_id=tenant_id,
                query=query,
                provider=provider,
                status=status,
                limit=limit,
            )
        except SupportIndexError as e:
            raise SupportResolveError(str(e)) from e

        if not matches:
            return {
                "answer": (
                    "No prior matching support resolutions were found. Sync and index more support "
                    "tickets or help-center articles before relying on automation for this issue."
                ),
                "confidence": "low",
                "citations": [],
                "matches": [],
                "next_action": "route_to_human",
            }

        answer = await self._generate_answer(query=query, matches=matches)
        return {
            "answer": answer,
            "confidence": self._confidence(matches),
            "citations": self._citations(matches),
            "matches": matches,
            "next_action": self._next_action(matches),
        }

    async def _generate_answer(self, *, query: str, matches: list[dict[str, Any]]) -> str:
        if _llm_client is None:
            return self._fallback_answer(query=query, matches=matches)

        context = "\n\n".join(
            f"[{idx}] {match.get('title') or match.get('source_id') or 'Support source'}\n"
            f"Provider: {match.get('provider') or 'unknown'}\n"
            f"Source type: {match.get('source_type') or 'unknown'}\n"
            f"Status: {match.get('status') or 'n/a'}\n"
            f"Snippet: {match.get('text') or ''}"
            for idx, match in enumerate(matches, start=1)
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "You are a customer support resolution analyst. Use only the supplied prior "
                    "tickets, comments, and help-center articles. Produce a concise resolution plan "
                    "with citations like [1]. If evidence is weak, say so and recommend human review."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Customer issue:\n{query}\n\nPrior support evidence:\n{context}\n\n"
                    "Return: likely cause, resolution steps, customer-facing response draft, and next action."
                ),
            },
        ]
        try:
            return await _llm_client.chat_completion(messages, temperature=0.2)
        except Exception as e:
            logger.warning("support resolve LLM failed, using fallback: %s", e, exc_info=True)
            return self._fallback_answer(query=query, matches=matches)

    def _fallback_answer(self, *, query: str, matches: list[dict[str, Any]]) -> str:
        top = matches[0]
        title = top.get("title") or top.get("source_id") or "matching support source"
        snippet = (top.get("text") or "").strip()
        return (
            f"Likely related prior resolution: {title} [1].\n\n"
            f"Evidence: {snippet[:800]}\n\n"
            "Suggested next step: review the cited ticket/article, confirm the customer environment matches, "
            "then reuse the proven resolution steps with a human support agent in the loop."
        )

    def _confidence(self, matches: list[dict[str, Any]]) -> str:
        top_score = matches[0].get("score") if matches else None
        if isinstance(top_score, (int, float)):
            if top_score >= 0.82 and len(matches) >= 2:
                return "high"
            if top_score >= 0.65:
                return "medium"
        return "medium" if len(matches) >= 3 else "low"

    def _next_action(self, matches: list[dict[str, Any]]) -> str:
        confidence = self._confidence(matches)
        if confidence == "high":
            return "suggest_agent_response"
        if confidence == "medium":
            return "agent_review"
        return "route_to_human"

    def _citations(self, matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations = []
        for idx, match in enumerate(matches, start=1):
            citations.append(
                {
                    "label": f"[{idx}]",
                    "provider": match.get("provider"),
                    "source_type": match.get("source_type"),
                    "source_id": match.get("source_id"),
                    "title": match.get("title"),
                    "source_url": match.get("source_url"),
                    "score": match.get("score"),
                }
            )
        return citations


support_resolver = SupportResolver()
