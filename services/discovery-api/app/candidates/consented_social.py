"""Consent-aware social candidates with redacted, deterministic evidence."""
from __future__ import annotations

import hashlib
import json
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

_MAX_MEMBERSHIPS = 10_000
_MAX_CANDIDATES = 1_000
_SOURCE = "consented_social"
_SOURCE_VERSION = "imd-consented-social-v1"
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class SocialMembership(BaseModel):
    """A bounded, consented aggregate; raw member identity is never returned."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    membership_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    group_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    experience_ids: tuple[str, ...] = Field(min_length=1, max_length=100)
    consent_state: ConsentState
    observed_at: datetime

    @model_validator(mode="after")
    def validate_membership(self) -> "SocialMembership":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if len(set(self.experience_ids)) != len(self.experience_ids):
            raise ValueError("experience IDs must be unique")
        return self


class SocialEvidence(BaseModel):
    """Stable evidence that contains no member or group identifiers."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    social_score: float = Field(ge=0, le=1, allow_inf_nan=False)
    group_count: int = Field(ge=1, le=_MAX_MEMBERSHIPS)
    relationship_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)


class ConsentedSocialResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[SocialEvidence, ...] = Field(max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_alignment(self) -> "ConsentedSocialResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


@dataclass(frozen=True)
class _ScoredCandidate:
    experience: ExperienceRecord
    score: float
    group_count: int
    digest: str


class ConsentedSocialCandidateSource:
    """Generate social candidates only from explicitly consented memberships."""

    source = _SOURCE

    def __init__(self, *, source_version: str = _SOURCE_VERSION, max_candidates: int = 20, max_memberships: int = 1_000) -> None:
        if not 1 <= max_candidates <= _MAX_CANDIDATES:
            raise ValueError("max_candidates is out of bounds")
        if not 1 <= max_memberships <= _MAX_MEMBERSHIPS:
            raise ValueError("max_memberships is out of bounds")
        self.source_version = source_version
        self.max_candidates = max_candidates
        self.max_memberships = max_memberships

    def retrieve(
        self,
        user: UserProfile,
        memberships: Iterable[SocialMembership],
        experiences: Iterable[ExperienceRecord],
        context: ImmersiveDiscoveryContext,
        *,
        as_of: datetime,
        blocked_ids: tuple[str, ...] = (),
        k: int | None = None,
    ) -> ConsentedSocialResult:
        _require_aware(as_of, "as_of")
        limit = self.max_candidates if k is None else k
        if not 1 <= limit <= _MAX_CANDIDATES:
            raise ValueError("k is out of bounds")
        tenant_id = context.request_context.tenant_id
        if user.tenant_id != tenant_id or context.request_context.principal_id != user.user_id:
            raise ValueError("user and request must share identity and tenant")
        if user.consent_state is ConsentState.PERSONALIZATION_DENIED:
            return self._result(context, (), (), Degradation.EMPTY)

        catalog = self._catalog(experiences, tenant_id)
        selected = self._memberships(memberships, user.user_id, tenant_id, as_of)
        if not selected:
            return self._result(context, (), (), Degradation.EMPTY)
        blocked = set(blocked_ids)
        grouped: dict[str, list[SocialMembership]] = {}
        for membership in selected:
            for experience_id in membership.experience_ids:
                if experience_id in catalog and experience_id not in blocked:
                    grouped.setdefault(experience_id, []).append(membership)

        scored: list[_ScoredCandidate] = []
        for experience_id, records in grouped.items():
            experience = catalog[experience_id]
            if not evaluate_eligibility(experience, user, context).eligible:
                continue
            groups = {record.group_id for record in records}
            score = min(1.0, 0.65 + 0.10 * min(len(groups), 3) + 0.05 * min(len(records), 3))
            digest = _digest(records)
            scored.append(_ScoredCandidate(experience, score, len(groups), digest))

        chosen = sorted(scored, key=lambda item: (-item.score, -item.group_count, item.experience.experience_id))[:limit]
        candidates = tuple(
            Candidate(
                experience_id=item.experience.experience_id,
                tenant_id=tenant_id,
                source=_SOURCE,
                source_version=self.source_version,
                score=item.score,
                reason_codes=("consented_social", "group_membership", "redacted_evidence"),
            )
            for item in chosen
        )
        evidence = tuple(
            SocialEvidence(
                experience_id=item.experience.experience_id,
                social_score=item.score,
                group_count=item.group_count,
                relationship_digest=item.digest,
                reason_codes=("consented_social", "group_membership", "redacted_evidence"),
            )
            for item in chosen
        )
        degradation = Degradation.OK if candidates else Degradation.EMPTY
        return self._result(context, candidates, evidence, degradation)

    def _memberships(self, memberships: Iterable[SocialMembership], user_id: str, tenant_id: str, as_of: datetime) -> tuple[SocialMembership, ...]:
        selected: list[SocialMembership] = []
        seen: set[str] = set()
        for membership in memberships:
            if membership.membership_id in seen:
                continue
            seen.add(membership.membership_id)
            if len(seen) > self.max_memberships:
                raise ValueError("membership input exceeds configured bound")
            if membership.tenant_id != tenant_id or membership.user_id != user_id:
                continue
            if membership.consent_state is not ConsentState.PERSONALIZATION_ALLOWED:
                continue
            if membership.observed_at > as_of:
                continue
            selected.append(membership)
        return tuple(selected)

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

    def _result(self, context: ImmersiveDiscoveryContext, candidates: tuple[Candidate, ...], evidence: tuple[SocialEvidence, ...], degradation: Degradation) -> ConsentedSocialResult:
        return ConsentedSocialResult(
            source_result=CandidateSourceResult(
                source=_SOURCE,
                source_version=self.source_version,
                tenant_id=context.request_context.tenant_id,
                request_id=context.request_context.request_id,
                candidates=candidates,
                degradation=degradation,
            ),
            evidence=evidence,
        )


def _digest(records: Iterable[SocialMembership]) -> str:
    canonical = [
        {"membership": record.membership_id, "groups": sorted(record.experience_ids), "observed_at": record.observed_at.isoformat()}
        for record in records
    ]
    payload = json.dumps(sorted(canonical, key=lambda item: item["membership"]), separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")
