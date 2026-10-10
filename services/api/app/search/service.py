from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.search.errors import normalize_opensearch_exception
from app.search.models import SearchRequest, SearchResponse

logger = logging.getLogger(__name__)

Fallback = Callable[[SearchRequest], Awaitable[SearchResponse]]
EventSink = Callable[[str, dict[str, Any]], None]


class SearchService:
    """Bounded search orchestration with an explicit, observable fallback."""

    def __init__(
        self,
        provider: Any,
        *,
        timeout_seconds: float = 5.0,
        fallback: Fallback | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("search timeout must be positive")
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.fallback = fallback
        self.event_sink = event_sink

    async def search(self, request: SearchRequest) -> SearchResponse:
        try:
            response = await asyncio.wait_for(
                self.provider.search(request),
                timeout=self.timeout_seconds,
            )
            self._emit("search.success", {"mode": request.mode.value, "result_count": len(response.results)})
            return response
        except asyncio.CancelledError:
            self._emit("search.cancelled", {"mode": request.mode.value})
            raise
        except Exception as error:
            normalized = normalize_opensearch_exception(error, operation="search")
            self._emit(
                "search.failure",
                {"mode": request.mode.value, "code": normalized.code, "retryable": normalized.retryable},
            )
            if self.fallback is None or not normalized.retryable:
                raise normalized from error
            logger.warning("search provider failed; using configured fallback: %s", normalized.code)
            self._emit("search.fallback", {"mode": request.mode.value, "code": normalized.code})
            return await asyncio.wait_for(self.fallback(request), timeout=self.timeout_seconds)

    def _emit(self, event: str, attributes: dict[str, Any]) -> None:
        if self.event_sink is None:
            return
        try:
            self.event_sink(event, attributes)
        except Exception:  # telemetry must never alter search behavior
            logger.debug("search telemetry failed", exc_info=True)


__all__ = ["SearchService"]
