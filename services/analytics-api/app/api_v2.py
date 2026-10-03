"""`/api/v2/analytics` governed endpoints (ADS-045).

The router is mounted but inert until a runtime is configured: with no `GovernedAnalyzeService`
or OIDC verifier every call returns 503, so nothing activates a production path by implication.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, Header, HTTPException, Response

from app.runtime.analyze_service import GovernedAnalyzeService, ServiceError
from app.security import AuthenticationError, OIDCVerifier
from packages.platform_contracts.analytics_v2_api import (
    AnalyzeRequest,
    AnalyzeRunResponse,
    ClarifyRequest,
    ReviewDecisionRequest,
)
from packages.platform_contracts.security import AnalyticsIdentity


@dataclass
class V2Runtime:
    service: GovernedAnalyzeService | None = None
    verifier: OIDCVerifier | None = None


def build_v2_router(runtime: V2Runtime, api_key_dependency) -> APIRouter:
    router = APIRouter(prefix="/api/v2/analytics", tags=["analytics-v2"], dependencies=[Depends(api_key_dependency)])

    def identity(authorization: str | None = Header(default=None)) -> AnalyticsIdentity:
        if runtime.service is None or runtime.verifier is None:
            raise HTTPException(503, "governed_runtime_not_configured")
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "missing_bearer_token", headers={"WWW-Authenticate": "Bearer"})
        try:
            return runtime.verifier.verify(token)
        except AuthenticationError as exc:
            raise HTTPException(401, "invalid_identity_token", headers={"WWW-Authenticate": "Bearer"}) from exc

    def respond(call, response: Response) -> AnalyzeRunResponse:
        try:
            result = call()
        except ServiceError as exc:
            raise HTTPException(exc.status, exc.code) from exc
        response.status_code = 202 if result.state == "running" else 200
        return result

    @router.post("/analyze", response_model=AnalyzeRunResponse)
    def analyze(
        body: AnalyzeRequest,
        response: Response,
        who: AnalyticsIdentity = Depends(identity),
        idempotency_key: str | None = Header(default=None),
    ):
        return respond(
            lambda: runtime.service.analyze(
                who, purpose=body.purpose, idempotency_key=idempotency_key or "", request_text=body.request_text
            ),
            response,
        )

    @router.get("/runs/{run_id}", response_model=AnalyzeRunResponse)
    def status(run_id: str, purpose: str, response: Response, who: AnalyticsIdentity = Depends(identity)):
        return respond(lambda: runtime.service.status(who, purpose=purpose, run_id=run_id), response)

    @router.post("/runs/{run_id}/clarify", response_model=AnalyzeRunResponse)
    def clarify(run_id: str, body: ClarifyRequest, response: Response, who: AnalyticsIdentity = Depends(identity)):
        return respond(
            lambda: runtime.service.clarify(
                who,
                purpose=body.purpose,
                run_id=run_id,
                ambiguity_code=body.ambiguity_code,
                selected_id=body.selected_id,
            ),
            response,
        )

    @router.post("/runs/{run_id}/review", response_model=AnalyzeRunResponse)
    def review(
        run_id: str, body: ReviewDecisionRequest, response: Response, who: AnalyticsIdentity = Depends(identity)
    ):
        return respond(
            lambda: runtime.service.decide_review(
                who,
                purpose=body.purpose,
                run_id=run_id,
                decision=body.decision,
                plan_fingerprint=body.plan_fingerprint,
                note=body.note,
            ),
            response,
        )

    return router
