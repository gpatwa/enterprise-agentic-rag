"""Public demo mode: anonymous visitors can try governed analysis on a separate, sample-only tenant.

Safety model (all server-side; the browser is never trusted):
- Off unless `ANALYTICS_DEMO_ENABLED`; the demo tenant must have its own certified contract on its own sample table.
- The identity is built here, never read from a token: the demo tenant, one fixed purpose, no groups. It can therefore never be
  a reviewer or the review assistant, and no review, feedback, or brief route exists under `/api/v2/demo`.
- Questions are length-limited and rate-limited per client address and per day for the whole demo, because each question can
  call a paid model. Limits are in memory (single replica) and fail closed.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import deque
from typing import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.runtime.analyze_service import ServiceError
from packages.platform_contracts.analytics_v2_api import AnalyzeRunResponse
from packages.platform_contracts.security import AnalyticsIdentity

DEMO_PURPOSE = "analytics"
_VISITOR = re.compile(r"^[A-Za-z0-9-]{16,64}$")
_MAX_TRACKED_ADDRESSES = 5_000


class DemoAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_text: str = Field(min_length=3, max_length=300)


class DemoClarifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ambiguity_code: str = Field(pattern="^(metric|dataset|grain|time|filter)$")
    selected_id: str = Field(min_length=1, max_length=255)


class DemoLimiter:
    """Sliding windows: questions per address per hour, and questions for the whole demo per day."""

    def __init__(self, per_address_hourly: int, global_daily: int, clock: Callable[[], float] = time.time) -> None:
        self._per_address, self._global_cap, self._clock = per_address_hourly, global_daily, clock
        self._addresses: dict[str, deque[float]] = {}
        self._global: deque[float] = deque()
        self._lock = threading.Lock()

    def admit(self, address: str) -> str | None:
        """Return None to admit and record the question, or the refusal code."""
        now = self._clock()
        with self._lock:
            while self._global and now - self._global[0] > 86_400:
                self._global.popleft()
            if len(self._global) >= self._global_cap:
                return "demo_daily_limit"
            window = self._addresses.get(address)
            if window is None:
                if len(self._addresses) >= _MAX_TRACKED_ADDRESSES:
                    self._prune(now)
                    if len(self._addresses) >= _MAX_TRACKED_ADDRESSES:
                        return "demo_busy"  # fail closed rather than grow without bound
                window = self._addresses[address] = deque()
            while window and now - window[0] > 3_600:
                window.popleft()
            if len(window) >= self._per_address:
                return "demo_rate_limited"
            window.append(now)
            self._global.append(now)
            return None

    def _prune(self, now: float) -> None:
        for key in [k for k, w in self._addresses.items() if not w or now - w[-1] > 3_600]:
            del self._addresses[key]


def client_address(request: Request) -> str:
    """The address the platform ingress recorded: the last forwarded hop (earlier hops are client-supplied)."""
    forwarded = request.headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    if hops:
        return hops[-1]
    return request.client.host if request.client else "unknown"


def demo_identity(tenant_id: str, visitor_id: str | None) -> AnalyticsIdentity:
    if not visitor_id or not _VISITOR.match(visitor_id):
        raise HTTPException(400, "demo_visitor_required")
    digest = hashlib.sha256(visitor_id.encode()).hexdigest()[:24]
    return AnalyticsIdentity(
        tenant_id=tenant_id, user_id=f"demo:{digest}", purposes=[DEMO_PURPOSE], groups=[], claims={}
    )


def build_demo_router(runtime, api_key_dependency, settings, limiter: DemoLimiter | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v2/demo", tags=["analytics-demo"], dependencies=[Depends(api_key_dependency)])
    limits = limiter or DemoLimiter(settings.ANALYTICS_DEMO_PER_ADDRESS_HOURLY, settings.ANALYTICS_DEMO_GLOBAL_DAILY)

    def enabled() -> None:
        if not settings.ANALYTICS_DEMO_ENABLED:
            raise HTTPException(404, "demo_disabled")
        if runtime.service is None:
            raise HTTPException(503, "governed_runtime_not_configured")

    def who(x_demo_visitor: str | None = Header(default=None)) -> AnalyticsIdentity:
        return demo_identity(settings.ANALYTICS_DEMO_TENANT, x_demo_visitor)

    def respond(call, response: Response) -> AnalyzeRunResponse:
        try:
            result = call()
        except ServiceError as exc:
            raise HTTPException(exc.status, exc.code) from exc
        response.status_code = 202 if result.state == "running" else 200
        return result

    @router.get("/status")
    def status() -> dict:
        return {"enabled": bool(settings.ANALYTICS_DEMO_ENABLED and runtime.service is not None)}

    @router.post("/analyze", response_model=AnalyzeRunResponse)
    def analyze(
        body: DemoAnalyzeRequest,
        request: Request,
        response: Response,
        identity: AnalyticsIdentity = Depends(who),
        idempotency_key: str | None = Header(default=None),
    ):
        enabled()
        refusal = limits.admit(client_address(request))
        if refusal:
            raise HTTPException(429, refusal)
        return respond(
            lambda: runtime.service.analyze(
                identity, purpose=DEMO_PURPOSE, idempotency_key=idempotency_key or "", request_text=body.request_text
            ),
            response,
        )

    @router.get("/runs/{run_id}", response_model=AnalyzeRunResponse)
    def run_status(run_id: str, response: Response, identity: AnalyticsIdentity = Depends(who)):
        enabled()
        return respond(lambda: runtime.service.status(identity, purpose=DEMO_PURPOSE, run_id=run_id), response)

    @router.post("/runs/{run_id}/clarify", response_model=AnalyzeRunResponse)
    def clarify(run_id: str, body: DemoClarifyRequest, response: Response, identity: AnalyticsIdentity = Depends(who)):
        enabled()
        return respond(
            lambda: runtime.service.clarify(
                identity,
                purpose=DEMO_PURPOSE,
                run_id=run_id,
                ambiguity_code=body.ambiguity_code,
                selected_id=body.selected_id,
            ),
            response,
        )

    return router
