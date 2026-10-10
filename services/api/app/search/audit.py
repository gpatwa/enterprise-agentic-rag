from __future__ import annotations

from typing import Any

from app.audit.manager import log_event
from app.search.models import SearchRequest, SearchResponse
from app.search.security import safe_audit_attributes


async def record_search_audit(
    request: SearchRequest,
    response: SearchResponse | None,
    *,
    success: bool,
    status_code: int,
    duration_ms: int | None = None,
) -> None:
    attributes: dict[str, Any] = {
        "request_id": request.request_id,
        "success": success,
        "mode": request.mode.value,
    }
    if response is not None:
        attributes.update(
            safe_audit_attributes(
                mode=request.mode.value,
                result_count=len(response.results),
                index_alias=response.index_alias,
                index_generation=response.index_generation,
            )
        )
    await log_event(
        tenant_id=request.scope.tenant_id,
        user_id=request.scope.principal_id,
        role=None,
        event_type="enterprise_search",
        request_id=request.request_id,
        status_code=status_code,
        duration_ms=duration_ms,
        pii_redacted=True,
        sources_used=[],
        payload_summary=f"mode={request.mode.value} success={success}",
        extra=attributes,
    )
