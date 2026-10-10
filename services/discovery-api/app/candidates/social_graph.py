"""Deterministic co-play and co-engagement graph candidates."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.domain.models import (
    ConsentState,
    ExperienceRecord,
    ImmersiveDiscoveryContext,
    UserProfile,
    evaluate_eligibility,
)
from app.events.models import EventType, InteractionEvent

_MAX_CANDIDATES = 1_000
_MAX_USERS = 10_000
_SOURCE = "social_graph"
_SOURCE_VERSION = "imd-coplay-graph-v1"


class CoPlayGraphConfig(BaseModel):
    """Versioned and bounded graph traversal and decay settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_version: str = Field(default=_SOURCE_VERSION, min_length=1, max_length=64)
    max_candidates: int = Field(default=20, ge=1, le=_MAX_CANDIDATES)
    max_users: int = Field(default=1_000, ge=1, le=_MAX_USERS)
    minimum_support: int = Field(default=1, ge=1, le=_MAX_USERS)
    half_life_seconds: float = Field(default=604_800.0, gt=0, le=31_536_000, allow_inf_nan=False)
    max_event_age_seconds: float = Field(default=31_536_000.0, ge=0, le=31_536_000, allow_inf_nan=False)


class CoPlayGraphEvidence(BaseModel):
    """Aggregate, redacted evidence for a graph candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255)
    support_count: int = Field(ge=1, le=_MAX_USERS)
    graph_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    co_play_signal: bool
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)


class CoPlayGraphResult(BaseModel):
    """Candidate output with no peer identity or private graph edge."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[CoPlayGraphEvidence, ...] = Field(max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_alignment(self) -> "CoPlayGraphResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


@dataclass(frozen=True)
class _ScoredCandidate:
    experience: ExperienceRecord
    score: float
    support_count: int
    co_play_signal: bool
    reasons: tuple[str, ...]


class CoPlayGraphCandidateSource:
    """Traverse a bounded local user-item graph without exposing peer identity."""

    source = _SOURCE

    def __init__(self, config: CoPlayGraphConfig | None = None) -> None:
        self.config = config or CoPlayGraphConfig()

    def retrieve(
        self,
        user: UserProfile,
        events: Iterable[InteractionEvent],
        experiences: Iterable[ExperienceRecord],
        context: ImmersiveDiscoveryContext,
        *,
        as_of: datetime,
        blocked_ids: tuple[str, ...] = (),
        k: int | None = None,
    ) -> CoPlayGraphResult:
        _require_aware(as_of, "as_of")
        limit = self.config.max_candidates if k is None else k
        if limit < 1 or limit > _MAX_CANDIDATES:
            raise ValueError(f"k must be between 1 and {_MAX_CANDIDATES}")
        tenant_id = context.request_context.tenant_id
        if user.tenant_id != tenant_id:
            raise ValueError("user and request must share a tenant")
        if user.consent_state is ConsentState.PERSONALIZATION_DENIED:
            return self._result(context, (), (), Degradation.EMPTY)

        catalog = self._catalog(experiences, tenant_id)
        qualified, co_play = self._events(events, tenant_id, as_of)
        target_items = {event.experience_id for event in qualified if event.user_id == user.user_id}
        if not target_items:
            return self._result(context, (), (), Degradation.EMPTY)

        peers_by_item: dict[str, set[str]] = {}
        items_by_user: dict[str, set[str]] = {}
        for event in qualified:
            items_by_user.setdefault(event.user_id, set()).add(event.experience_id)
            if event.experience_id in target_items and event.user_id != user.user_id:
                peers_by_item.setdefault(event.experience_id, set()).add(event.user_id)
        peers = {peer for values in peers_by_item.values() for peer in values}
        if len(peers) > self.config.max_users:
            raise ValueError(f"graph traversal exceeds max_users={self.config.max_users}")

        support: dict[str, set[str]] = {}
        score: dict[str, float] = {}
        co_play_items = {event.experience_id for event in co_play}
        for anchor in sorted(target_items):
            anchor_peers = peers_by_item.get(anchor, set())
            for peer in sorted(anchor_peers):
                for candidate_id in items_by_user.get(peer, set()):
                    if candidate_id in target_items or candidate_id in blocked_ids or candidate_id not in catalog:
                        continue
                    support.setdefault(candidate_id, set()).add(peer)
                    score[candidate_id] = score.get(candidate_id, 0.0) + self._decay(
                        next(event.occurred_at for event in qualified if event.user_id == peer and event.experience_id == candidate_id),
                        as_of,
                    )

        scored: list[_ScoredCandidate] = []
        for experience_id, peers_for_candidate in support.items():
            support_count = len(peers_for_candidate)
            if support_count < self.config.minimum_support:
                continue
            experience = catalog[experience_id]
            if not evaluate_eligibility(experience, user, context).eligible:
                continue
            co_play_signal = any(anchor in co_play_items for anchor in target_items)
            raw = score[experience_id] / max(1, support_count)
            graph_score = _bounded(0.8 * raw + (0.2 if co_play_signal else 0.0))
            reasons = ("shared_co_engagement", "qualified_support", "time_decay")
            if co_play_signal:
                reasons += ("co_play_signal",)
            scored.append(_ScoredCandidate(experience, graph_score, support_count, co_play_signal, reasons))

        selected = sorted(scored, key=lambda item: (-item.score, -item.support_count, item.experience.experience_id))[:limit]
        candidates = tuple(
            Candidate(
                experience_id=item.experience.experience_id,
                tenant_id=tenant_id,
                source=_SOURCE,
                source_version=self.config.source_version,
                score=item.score,
                reason_codes=item.reasons,
            )
            for item in selected
        )
        evidence = tuple(
            CoPlayGraphEvidence(
                experience_id=item.experience.experience_id,
                support_count=item.support_count,
                graph_score=item.score,
                co_play_signal=item.co_play_signal,
                reason_codes=item.reasons,
            )
            for item in selected
        )
        return self._result(context, candidates, evidence, Degradation.OK if candidates else Degradation.EMPTY)

    def _events(
        self,
        events: Iterable[InteractionEvent],
        tenant_id: str,
        as_of: datetime,
    ) -> tuple[tuple[InteractionEvent, ...], tuple[InteractionEvent, ...]]:
        qualified: list[InteractionEvent] = []
        co_play: list[InteractionEvent] = []
        seen: set[str] = set()
        for event in events:
            if event.tenant_id != tenant_id or event.event_id in seen:
                continue
            seen.add(event.event_id)
            if event.occurred_at > as_of:
                continue
            if (as_of - event.occurred_at).total_seconds() > self.config.max_event_age_seconds:
                continue
            if event.consent_state is not ConsentState.PERSONALIZATION_ALLOWED:
                continue
            if event.event_type is EventType.QUALIFIED_PLAY:
                qualified.append(event)
            elif event.event_type is EventType.CO_PLAY:
                co_play.append(event)
        qualified.sort(key=lambda event: (event.occurred_at, event.event_id))
        co_play.sort(key=lambda event: (event.occurred_at, event.event_id))
        return tuple(qualified), tuple(co_play)

    @staticmethod
    def _catalog(experiences: Iterable[ExperienceRecord], tenant_id: str) -> dict[str, ExperienceRecord]:
        catalog: dict[str, ExperienceRecord] = {}
        for experience in experiences:
            if experience.tenant_id != tenant_id:
                continue
            if experience.experience_id in catalog:
                raise ValueError("duplicate experience record")
            catalog[experience.experience_id] = experience
        return catalog

    def _decay(self, occurred_at: datetime, as_of: datetime) -> float:
        age = max(0.0, (as_of - occurred_at).total_seconds())
        return math.exp(-math.log(2.0) * age / self.config.half_life_seconds)

    def _result(
        self,
        context: ImmersiveDiscoveryContext,
        candidates: tuple[Candidate, ...],
        evidence: tuple[CoPlayGraphEvidence, ...],
        degradation: Degradation,
    ) -> CoPlayGraphResult:
        return CoPlayGraphResult(
            source_result=CandidateSourceResult(
                source=_SOURCE,
                source_version=self.config.source_version,
                tenant_id=context.request_context.tenant_id,
                request_id=context.request_context.request_id,
                candidates=candidates,
                degradation=degradation,
            ),
            evidence=evidence,
        )


def _bounded(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("graph scores must be finite")
    return max(0.0, min(1.0, value))


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
