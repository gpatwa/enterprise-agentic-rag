# services/api/app/support/resolver.py
from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

from app.config import settings
from app.support.indexer import SupportIndexError, support_indexer
from app.tracing import set_span_attributes, start_span

logger = logging.getLogger(__name__)

_llm_client = None
_CITATION_RE = re.compile(r"\[(\d+)\]")


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
        session: Any = None,
    ) -> dict[str, Any]:
        query = " ".join(question.split())
        if len(query) < 2:
            raise SupportResolveError("question must be at least 2 characters")

        with start_span(
            "support.resolve",
            tenant_id=tenant_id,
            provider=provider or "all",
            status=status or "any",
            limit=limit,
            question_length=len(query),
        ) as span:
            try:
                matches = await support_indexer.search(
                    tenant_id=tenant_id,
                    query=query,
                    provider=provider,
                    status=status,
                    limit=limit,
                    session=session,
                )
            except SupportIndexError as e:
                raise SupportResolveError(str(e)) from e

            if not matches:
                set_span_attributes(
                    span,
                    match_count=0,
                    confidence="low",
                    citation_count=0,
                    next_action="route_to_human",
                )
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

            with start_span(
                "support.resolve.llm",
                tenant_id=tenant_id,
                provider=provider or "all",
                match_count=len(matches),
                llm_configured=_llm_client is not None,
            ) as llm_span:
                answer = await self._generate_answer(query=query, matches=matches)
                set_span_attributes(llm_span, answer_length=len(answer or ""))

            answer, verification_status = self._verified_answer(
                query=query,
                answer=answer,
                matches=matches,
            )
            confidence = self._confidence(matches)
            citations = self._citations(matches)
            next_action = self._next_action(matches)
            set_span_attributes(
                span,
                match_count=len(matches),
                confidence=confidence,
                citation_count=len(citations),
                next_action=next_action,
                citation_verification_status=verification_status,
            )
            return {
                "answer": answer,
                "confidence": confidence,
                "citations": citations,
                "matches": matches,
                "next_action": next_action,
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
            return await asyncio.wait_for(
                _llm_client.chat_completion(messages, temperature=0.2),
                timeout=settings.SUPPORT_RESOLVE_LLM_TIMEOUT_SECONDS,
            )
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

    def _verified_answer(
        self,
        *,
        query: str,
        answer: str,
        matches: list[dict[str, Any]],
    ) -> tuple[str, str]:
        """Require generated answers to cite only retrieved evidence labels."""
        allowed = {str(idx) for idx in range(1, len(matches) + 1)}
        referenced = set(_CITATION_RE.findall(answer or ""))
        if referenced and referenced.issubset(allowed):
            return answer, "verified"

        if referenced:
            logger.warning(
                "support resolve answer had unverifiable citation labels: referenced=%s allowed=%s",
                sorted(referenced),
                sorted(allowed),
            )
            verification_status = "invalid_citations"
        else:
            logger.info("support resolve answer had no citations; using deterministic fallback")
            verification_status = "missing_citations"
        return self._fallback_answer(query=query, matches=matches), verification_status

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
