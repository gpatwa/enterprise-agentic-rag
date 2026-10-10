"""Typed, local-only immersive discovery search endpoint."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Protocol

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import ImmersiveDiscoveryContext, UserProfile
from app.policy.eligibility import compile_eligibility
from app.query.parser import parse_query
from app.ranking.router import (
    RankingMode,
    RankingStageRouter,
    RouterCandidate,
    StageConfig,
    StageName,
    StageOutput,
    StageRouterRequest,
)
from app.search.fusion import FusionConfig, fuse_candidates
from app.search.lexical import LexicalRetriever
from app.search.mapper import CatalogSearchDocument
from packages.platform_contracts.discovery import (
    DecisionTrace,
    DiscoveryComponentVersion,
    DiscoveryRequestContext,
    ImpressionToken,
)

_MAX_RESULTS = 50
_MAX_QUERY = 256
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = "imd-search-v1"


class SearchRequest(BaseModel):
    """Bounded search input; profiles and vectors are never accepted here."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query: str = Field(min_length=1, max_length=_MAX_QUERY)
    context: DiscoveryRequestContext
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=_MAX_RESULTS)
    blocked_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=1000)

    @model_validator(mode="after")
    def validate_query(self) -> "SearchRequest":
        if not self.query.strip():
            raise ValueError("query must contain searchable characters")
        if any(not value.strip() for value in self.blocked_ids):
            raise ValueError("blocked IDs must be non-blank")
        return self


class SearchResult(BaseModel):
    """Public result envelope with redacted, bounded evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    title: str = Field(min_length=1, max_length=255)
    rank: int = Field(ge=1, le=_MAX_RESULTS)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=12)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=12)


class QuerySummary(BaseModel):
    """Safe query metadata; lexical text and exact terms never leave the service."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query_version: str = Field(min_length=1, max_length=64)
    is_empty: bool
    locale: str | None = Field(default=None, max_length=32)
    device: str | None = Field(default=None, max_length=32)
    age_rating: str | None = Field(default=None, max_length=16)
    genres: tuple[str, ...] = Field(default_factory=tuple, max_length=10)
    themes: tuple[str, ...] = Field(default_factory=tuple, max_length=10)


class SearchError(BaseModel):
    """Typed fail-closed error without identifiers or private context."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    message: str = Field(min_length=1, max_length=160)


class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = _VERSION
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    results: tuple[SearchResult, ...] = Field(max_length=_MAX_RESULTS)
    total_matches: int = Field(ge=0, le=1_000_000)
    query: QuerySummary | None = None
    components: tuple[DiscoveryComponentVersion, ...] = Field(min_length=1, max_length=12)
    impression_token: ImpressionToken | None = None
    decision_trace: DecisionTrace | None = None
    fallback: bool = False
    error: SearchError | None = None

    @model_validator(mode="after")
    def validate_error_shape(self) -> "SearchResponse":
        if self.error is not None and (self.results or self.impression_token is not None):
            raise ValueError("failed responses cannot expose results or impression tokens")
        return self


class SearchProvider(Protocol):
    def search(self, request: SearchRequest) -> SearchResponse: ...


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _component(component_type: str, name: str, version: str) -> DiscoveryComponentVersion:
    return DiscoveryComponentVersion(
        component_type=component_type,
        name=name,
        version=version,
        digest=_digest({"name": name, "version": version}),
    )


def _components() -> tuple[DiscoveryComponentVersion, ...]:
    return (
        _component("schema", "imd-search", _VERSION),
        _component("artifact", "imd-query-parser", "imd-query-v1"),
        _component("policy", "imd-eligibility", "imd-eligibility-v1"),
        _component("index", "imd-catalog", "imd-lexical-v1"),
        _component("artifact", "imd-ranking-router", "imd-ranking-v1"),
    )


class LocalSearchService:
    """Compose deterministic local contracts over supplied catalog fixtures."""

    def __init__(
        self,
        documents: tuple[CatalogSearchDocument, ...] = (),
        profiles: tuple[UserProfile, ...] = (),
    ) -> None:
        self._documents = tuple(documents)
        self._profiles = tuple(profiles)
        self._retriever = LexicalRetriever()

    def search(self, request: SearchRequest) -> SearchResponse:
        started = datetime.now(timezone.utc)
        components = _components()
        profile = next(
            (
                item
                for item in self._profiles
                if item.tenant_id == request.context.tenant_id
                and item.user_id == request.context.principal_id
            ),
            None,
        )
        context = ImmersiveDiscoveryContext(request_context=request.context, surface="search")
        try:
            eligibility = compile_eligibility(
                request.context,
                profile,
                blocked_ids=request.blocked_ids,
                personalization_requested=False,
            )
        except (TypeError, ValueError):
            return self._failure(request, components, "invalid_search_context", started)
        if not eligibility.eligible:
            return self._failure(request, components, eligibility.reason.value, started)
        try:
            parsed = parse_query(request.query)
            lexical = self._retriever.retrieve(
                parsed.lexical_text or request.query,
                self._documents,
                context,
                profile,
                source_version="imd-lexical-v1",
            )
            filtered = tuple(
                candidate
                for candidate in lexical.source_result.candidates
                if candidate.experience_id not in set(request.blocked_ids)
            )
            source = lexical.source_result.model_copy(update={"candidates": filtered})
            fused = fuse_candidates(
                (source,),
                tenant_id=request.context.tenant_id,
                request_id=request.context.request_id,
                config=FusionConfig(limit=_MAX_RESULTS),
            )
            routed = self._route(request, fused.candidates)
            by_id = {document.experience_id: document for document in self._documents}
            evidence_by_id = {item.experience_id: item for item in lexical.evidence}
            results = tuple(
                SearchResult(
                    experience_id=item.candidate_id,
                    title=by_id[item.candidate_id].title,
                    rank=rank,
                    score=min(1.0, item.score),
                    reason_codes=item.reason_codes,
                    evidence=evidence_by_id.get(item.candidate_id).matched_fields
                    if evidence_by_id.get(item.candidate_id) is not None
                    else (),
                )
                for rank, item in enumerate(routed.candidates, start=1)
            )
            page_start = (request.page - 1) * request.page_size
            page = results[page_start : page_start + request.page_size]
            token = self._token(request.context, components, page)
            summary = QuerySummary(
                query_version=parsed.query_version,
                is_empty=parsed.is_empty,
                locale=parsed.constraints.locale.value if parsed.constraints.locale else None,
                device=parsed.constraints.device.value if parsed.constraints.device else None,
                age_rating=parsed.constraints.age_rating.value if parsed.constraints.age_rating else None,
                genres=tuple(item.value for item in parsed.constraints.genres),
                themes=tuple(item.value for item in parsed.constraints.themes),
            )
            completed = datetime.now(timezone.utc)
            trace = DecisionTrace(
                trace_id=_digest({"request": request.context.request_id, "result": [item.experience_id for item in page]}),
                tenant_id=request.context.tenant_id,
                principal_id=request.context.principal_id,
                request_id=request.context.request_id,
                started_at=started,
                completed_at=completed,
                stages=(
                    {"stage": "eligibility", "outcome": "completed", "duration_ms": 0, "candidate_count": len(self._documents), "reason_codes": (eligibility.reason.value,), "components": (components[2],)},
                    {"stage": "retrieval", "outcome": "completed", "duration_ms": 0, "candidate_count": len(lexical.source_result.candidates), "reason_codes": ("lexical",), "components": (components[3],)},
                    {"stage": "fusion", "outcome": "completed", "duration_ms": 0, "candidate_count": len(fused.candidates), "reason_codes": ("rrf",), "components": (components[3],)},
                    {"stage": "rank", "outcome": "degraded" if routed.fallback else "completed", "duration_ms": 0, "candidate_count": len(routed.candidates), "reason_codes": tuple(decision.fallback_reason.value for decision in routed.trace if decision.fallback_reason.value != "none"), "components": (components[4],)},
                ),
            )
            return SearchResponse(
                request_id=request.context.request_id,
                results=page,
                total_matches=len(filtered),
                query=summary,
                components=components,
                impression_token=token,
                decision_trace=trace,
                fallback=routed.fallback,
            )
        except (TypeError, ValueError):
            return self._failure(request, components, "invalid_search_request", started)

    @staticmethod
    def _route(request: SearchRequest, candidates: tuple) -> object:
        inputs = tuple(
            RouterCandidate(
                candidate_id=item.experience_id,
                score=min(1.0, item.score),
                original_rank=rank,
                reason_codes=item.reason_codes,
            )
            for rank, item in enumerate(candidates, start=1)
        )
        if not inputs:
            return RankingStageRouter().route(
                StageRouterRequest(request_id=request.context.request_id, mode=RankingMode.HYBRID_ONLY, candidates=(RouterCandidate(candidate_id="empty"),))
            ).model_copy(update={"candidates": ()})
        return RankingStageRouter(
            stages={StageName.HYBRID: lambda values: StageOutput(candidates=values)},
            configs=(StageConfig(stage=StageName.HYBRID, component_version="imd-hybrid-v1"),),
        ).route(StageRouterRequest(request_id=request.context.request_id, mode=RankingMode.HYBRID_ONLY, candidates=inputs))

    @staticmethod
    def _token(context: DiscoveryRequestContext, components: tuple[DiscoveryComponentVersion, ...], results: tuple[SearchResult, ...]) -> ImpressionToken:
        issued = datetime.now(timezone.utc)
        token_id = _digest({"context": context.model_dump(mode="json"), "results": [item.experience_id for item in results]})
        return ImpressionToken.for_context(
            context,
            token_id=token_id,
            issued_at=issued,
            expires_at=issued + timedelta(minutes=15),
            schema_version=_VERSION,
            components=components,
        )

    @staticmethod
    def _failure(request: SearchRequest, components: tuple[DiscoveryComponentVersion, ...], code: str, started: datetime) -> SearchResponse:
        return SearchResponse(
            request_id=request.context.request_id,
            results=(),
            total_matches=0,
            components=components,
            decision_trace=None,
            error=SearchError(code=code, message="Search context was rejected"),
        )


service: SearchProvider = LocalSearchService()
router = APIRouter(tags=["discovery"])


@router.post("/v1/search", response_model=SearchResponse)
def search(request: SearchRequest) -> SearchResponse:
    """Run local discovery search through the configured provider."""
    return service.search(request)


__all__ = [
    "LocalSearchService",
    "SearchError",
    "SearchRequest",
    "SearchResponse",
    "SearchResult",
    "QuerySummary",
    "router",
    "search",
]
