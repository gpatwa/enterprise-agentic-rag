"""Typed, local-only personalized home endpoint."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Iterable, Protocol

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import (
    ExperienceRecord,
    HistoryLength,
    ImmersiveDiscoveryContext,
    Persona,
    UserProfile,
    evaluate_eligibility,
)
from packages.platform_contracts.discovery import (
    DecisionTrace,
    DiscoveryComponentVersion,
    DiscoveryRequestContext,
    ImpressionToken,
)

_MAX_RESULTS = 50
_MAX_BLOCKED = 1_000
_VERSION = "imd-home-v1"
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class HomeRequest(BaseModel):
    """Bounded home input; personalization features are never accepted from callers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    context: DiscoveryRequestContext
    page_size: int = Field(default=20, ge=1, le=_MAX_RESULTS)
    persona: Persona | None = None
    blocked_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_BLOCKED)

    @model_validator(mode="after")
    def validate_request(self) -> "HomeRequest":
        if any(not value.strip() for value in self.blocked_ids):
            raise ValueError("blocked IDs must be non-blank")
        if len(set(self.blocked_ids)) != len(self.blocked_ids):
            raise ValueError("blocked IDs must be unique")
        if self.context.purpose != "home":
            raise ValueError("home requests require the home purpose")
        return self


class HomeResult(BaseModel):
    """Public catalog result; no profile, history, or social features are returned."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    title: str = Field(min_length=1, max_length=255)
    rank: int = Field(ge=1, le=_MAX_RESULTS)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=12)


class HomeError(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    message: str = Field(min_length=1, max_length=160)


class HomeResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = _VERSION
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    persona: Persona
    personalization_allowed: bool
    results: tuple[HomeResult, ...] = Field(max_length=_MAX_RESULTS)
    sources: tuple[str, ...] = Field(min_length=1, max_length=12)
    reasons: tuple[str, ...] = Field(min_length=1, max_length=12)
    components: tuple[DiscoveryComponentVersion, ...] = Field(min_length=1, max_length=12)
    impression_token: ImpressionToken | None = None
    decision_trace: DecisionTrace | None = None
    fallback: bool = False
    error: HomeError | None = None

    @model_validator(mode="after")
    def validate_error_shape(self) -> "HomeResponse":
        if self.error is not None and (self.results or self.impression_token is not None):
            raise ValueError("failed responses cannot expose results or impression tokens")
        return self


class HomeProvider(Protocol):
    def home(self, request: HomeRequest) -> HomeResponse: ...


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
        _component("schema", "imd-home", _VERSION),
        _component("policy", "imd-eligibility", "imd-eligibility-v1"),
        _component("artifact", "imd-home-orchestrator", "imd-home-orchestration-v1"),
        _component("artifact", "imd-safe-diversity", "imd-diversity-v1"),
    )


class LocalHomeService:
    """Compose bounded deterministic home results from supplied local fixtures."""

    def __init__(
        self,
        experiences: tuple[ExperienceRecord, ...] = (),
        profiles: tuple[UserProfile, ...] = (),
    ) -> None:
        self._experiences = tuple(experiences)
        self._profiles = tuple(profiles)

    def home(self, request: HomeRequest) -> HomeResponse:
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
        if profile is None:
            return self._failure(request, components, "missing_context")
        try:
            discovery_context = ImmersiveDiscoveryContext(
                request_context=request.context,
                surface="home",
            )
            if profile.tenant_id != request.context.tenant_id:
                return self._failure(request, components, "tenant_scope_mismatch")
            allowed = profile.consent_state.value == "personalization_allowed"
            personalized = allowed and profile.history_length is not HistoryLength.NONE
            persona = request.persona or (profile.persona if personalized else Persona.NO_PERSONALIZATION)
            candidates = self._eligible(request, profile, discovery_context)
            ranked = self._rank(candidates, profile, personalized, request.context.request_id)
            page = tuple(ranked[: request.page_size])
            results = tuple(
                HomeResult(
                    experience_id=item.experience.experience_id,
                    title=item.experience.title,
                    rank=index,
                    score=item.score,
                    source=item.source,
                    reason_codes=item.reasons,
                )
                for index, item in enumerate(page, start=1)
            )
            fallback = not personalized
            fallback_reason = (
                "personalization_consent_denied"
                if not allowed
                else "no_history"
                if profile.history_length is HistoryLength.NONE
                else "personalized"
            )
            token = self._token(request.context, components, results)
            trace = DecisionTrace(
                trace_id=_digest({"request": request.context.request_id, "results": [item.experience_id for item in results]}),
                tenant_id=request.context.tenant_id,
                principal_id=request.context.principal_id,
                request_id=request.context.request_id,
                started_at=started,
                completed_at=datetime.now(timezone.utc),
                stages=(
                    {"stage": "eligibility", "outcome": "completed", "duration_ms": 0, "candidate_count": len(candidates), "reason_codes": ("hard_policy_enforced",), "components": (components[1],)},
                    {"stage": "retrieval", "outcome": "completed", "duration_ms": 0, "candidate_count": len(candidates), "reason_codes": ("personalized" if personalized else "safe_catalog_fallback",), "components": (components[2],)},
                    {"stage": "rerank", "outcome": "degraded" if fallback else "completed", "duration_ms": 0, "candidate_count": len(ranked), "reason_codes": (fallback_reason,), "components": (components[3],)},
                ),
            )
            return HomeResponse(
                request_id=request.context.request_id,
                persona=persona,
                personalization_allowed=personalized,
                results=results,
                sources=tuple(dict.fromkeys(item.source for item in page)) or ("safe_catalog_fallback",),
                reasons=tuple(dict.fromkeys((fallback_reason, *(reason for item in page for reason in item.reasons)))),
                components=components,
                impression_token=token,
                decision_trace=trace,
                fallback=fallback,
            )
        except (TypeError, ValueError):
            return self._failure(request, components, "invalid_home_context")

    def _eligible(
        self,
        request: HomeRequest,
        profile: UserProfile,
        context: ImmersiveDiscoveryContext,
    ) -> tuple[ExperienceRecord, ...]:
        blocked = set(request.blocked_ids)
        selected: list[ExperienceRecord] = []
        for experience in self._experiences:
            if experience.experience_id in blocked:
                continue
            if evaluate_eligibility(experience, profile, context).eligible:
                selected.append(experience)
        return tuple(selected)

    @staticmethod
    def _rank(
        experiences: Iterable[ExperienceRecord],
        profile: UserProfile,
        personalized: bool,
        request_id: str,
    ) -> tuple["_HomeCandidate", ...]:
        scored: list[_HomeCandidate] = []
        preferences = set(profile.preferences.genres) | set(profile.preferences.themes)
        for experience in experiences:
            quality = 1.0 if experience.signals and experience.signals.quality_band.value == "high" else 0.6
            popularity = 1.0 if experience.signals and experience.signals.popularity_band.value == "popular" else 0.5
            match = len(preferences & (set(experience.genres) | set(experience.themes))) / max(len(preferences), 1)
            score = min(1.0, 0.45 * quality + 0.25 * popularity + (0.30 * match if personalized else 0.0))
            source = "personalized" if personalized else "safe_catalog_fallback"
            reasons = ("hard_eligibility", "quality", "popularity", "preference_match") if personalized else ("hard_eligibility", "quality", "diversity_fallback")
            digest = _digest({"request": request_id, "experience": experience.experience_id})
            scored.append(_HomeCandidate(experience, score, source, reasons, digest))
        ordered = sorted(scored, key=lambda item: (-item.score, item.digest, item.experience.experience_id))
        chosen: list[_HomeCandidate] = []
        creator_counts: dict[str, int] = {}
        genre_counts: dict[str, int] = {}
        for item in ordered:
            if creator_counts.get(item.experience.creator_id, 0) >= 2:
                continue
            primary_genre = item.experience.genres[0].value
            if genre_counts.get(primary_genre, 0) >= 3 and len(chosen) < len(ordered) - 1:
                continue
            creator_counts[item.experience.creator_id] = creator_counts.get(item.experience.creator_id, 0) + 1
            genre_counts[primary_genre] = genre_counts.get(primary_genre, 0) + 1
            chosen.append(item)
        return tuple(chosen)

    @staticmethod
    def _token(context: DiscoveryRequestContext, components: tuple[DiscoveryComponentVersion, ...], results: tuple[HomeResult, ...]) -> ImpressionToken:
        issued = datetime.now(timezone.utc)
        return ImpressionToken.for_context(
            context,
            token_id=_digest({"context": context.model_dump(mode="json"), "results": [item.experience_id for item in results]}),
            issued_at=issued,
            expires_at=issued + timedelta(minutes=15),
            schema_version=_VERSION,
            components=components,
        )

    @staticmethod
    def _failure(request: HomeRequest, components: tuple[DiscoveryComponentVersion, ...], code: str) -> HomeResponse:
        return HomeResponse(
            request_id=request.context.request_id,
            persona=Persona.NO_PERSONALIZATION,
            personalization_allowed=False,
            results=(),
            sources=("safe_catalog_fallback",),
            reasons=(code,),
            components=components,
            error=HomeError(code=code, message="Home context was rejected"),
        )


class _HomeCandidate:
    def __init__(self, experience: ExperienceRecord, score: float, source: str, reasons: tuple[str, ...], digest: str) -> None:
        self.experience = experience
        self.score = score
        self.source = source
        self.reasons = reasons
        self.digest = digest


service: HomeProvider = LocalHomeService()
router = APIRouter(tags=["discovery"])


@router.post("/v1/home", response_model=HomeResponse)
def home(request: HomeRequest) -> HomeResponse:
    """Return a local personalized or safe fallback home feed."""
    return service.home(request)


__all__ = ["HomeRequest", "HomeResponse", "HomeResult", "LocalHomeService", "home", "router"]
