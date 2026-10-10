"""Deterministic integrity defenses for discovery interaction signals.

The module deliberately accepts approved digests rather than raw identity values.
It produces bounded evidence and never lets flagged signals enter ranking inputs
until a separate review process clears them.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timedelta
from enum import Enum
from typing import Iterable, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator

_DIGEST = r"^[0-9a-f]{64}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
_LABEL = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$"
_MAX_SIGNALS = 10_000


class _IntegrityModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SignalType(str, Enum):
    IMPRESSION = "impression"
    CLICK = "click"
    DETAIL_VIEW = "detail_view"
    PLAY = "play"
    QUALIFIED_PLAY = "qualified_play"
    PLAYTIME = "playtime"
    SAVE = "save"
    DISMISS = "dismiss"
    REPORT = "report"
    INVITE = "invite"
    CO_PLAY = "co_play"
    RETURN = "return"
    RETENTION = "retention"
    ORGANIC_NAVIGATION = "organic_navigation"


class EvidenceCode(str, Enum):
    DUPLICATE_EVENT = "duplicate_event"
    DUPLICATE_SEMANTIC_EVENT = "duplicate_semantic_event"
    IMPOSSIBLE_SEQUENCE = "impossible_sequence"
    IMPOSSIBLE_TIMING = "impossible_timing"
    ACTOR_RATE_LIMIT = "actor_rate_limit"
    TENANT_RATE_LIMIT = "tenant_rate_limit"
    COORDINATED_BURST = "coordinated_burst"
    POPULARITY_LOOP = "popularity_loop"
    UNSAFE_SIGNAL = "unsafe_signal"


class IntegrityStatus(str, Enum):
    CLEAN = "clean"
    FLAGGED = "flagged"
    REJECTED = "rejected"


class IntegrityPolicy(_IntegrityModel):
    """Versioned, bounded thresholds for local integrity evaluation."""

    policy_version: str = Field(default="v1", pattern=_VERSION)
    window_seconds: int = Field(default=60, ge=1, le=86_400)
    min_event_spacing_seconds: float = Field(default=0.05, gt=0, le=3_600, allow_inf_nan=False)
    max_actor_events_per_window: int = Field(default=120, ge=1, le=100_000)
    max_tenant_events_per_window: int = Field(default=10_000, ge=1, le=1_000_000)
    coordinated_actor_count: int = Field(default=25, ge=2, le=100_000)
    coordinated_burst_events: int = Field(default=50, ge=2, le=1_000_000)
    max_actions_per_impression: float = Field(default=8.0, ge=0, le=1_000_000, allow_inf_nan=False)
    min_popularity_actions: int = Field(default=20, ge=1, le=1_000_000)


class IntegritySignal(_IntegrityModel):
    """A bounded event observation containing only approved digests."""

    event_digest: str = Field(pattern=_DIGEST)
    tenant_digest: str = Field(pattern=_DIGEST)
    actor_digest: str = Field(pattern=_DIGEST)
    experience_digest: str = Field(pattern=_DIGEST)
    occurred_at: datetime
    signal_type: SignalType
    synthetic: bool
    source: str = Field(default="recommendation", min_length=1, max_length=64, pattern=_LABEL)
    impression_digest: str | None = Field(default=None, pattern=_DIGEST)

    @model_validator(mode="after")
    def validate_timestamp(self) -> "IntegritySignal":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.signal_type is SignalType.ORGANIC_NAVIGATION and self.source not in {"organic", "direct_navigation"}:
            raise ValueError("organic navigation requires an organic source")
        return self

    def fingerprint(self) -> str:
        """Return a stable semantic fingerprint without exposing raw identity."""
        value = f"{self.tenant_digest}:{self.actor_digest}:{self.experience_digest}:{self.signal_type.value}:{self.occurred_at.isoformat()}"
        return hashlib.sha256(value.encode("ascii")).hexdigest()


class IntegrityEvidence(_IntegrityModel):
    event_digest: str = Field(pattern=_DIGEST)
    code: EvidenceCode
    policy_version: str = Field(pattern=_VERSION)
    related_digest: str | None = Field(default=None, pattern=_DIGEST)
    detail: str = Field(min_length=1, max_length=96, pattern=_LABEL)


class IntegrityAssessment(_IntegrityModel):
    schema_version: str = Field(default="v1", pattern=_VERSION)
    policy_version: str = Field(pattern=_VERSION)
    status: IntegrityStatus
    reviewed: bool = False
    total_signals: int = Field(ge=0, le=_MAX_SIGNALS)
    flagged_count: int = Field(ge=0, le=_MAX_SIGNALS)
    ranking_eligible_event_digests: tuple[str, ...] = Field(max_length=_MAX_SIGNALS)
    flagged_event_digests: tuple[str, ...] = Field(max_length=_MAX_SIGNALS)
    evidence: tuple[IntegrityEvidence, ...] = Field(max_length=_MAX_SIGNALS)

    @model_validator(mode="after")
    def validate_counts(self) -> "IntegrityAssessment":
        if self.total_signals != len(set(self.ranking_eligible_event_digests) | set(self.flagged_event_digests)):
            raise ValueError("assessment counts must cover each unique signal")
        if self.flagged_count != len(self.flagged_event_digests):
            raise ValueError("flagged_count must match flagged event digests")
        if set(self.ranking_eligible_event_digests) & set(self.flagged_event_digests):
            raise ValueError("flagged events cannot be ranking eligible")
        return self

    def serialize(self) -> str:
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=True, separators=(",", ":"), sort_keys=True)


_ACTIONS = frozenset(
    {
        SignalType.CLICK,
        SignalType.DETAIL_VIEW,
        SignalType.PLAY,
        SignalType.QUALIFIED_PLAY,
        SignalType.PLAYTIME,
        SignalType.SAVE,
        SignalType.INVITE,
        SignalType.CO_PLAY,
    }
)
_PRIOR_EVENTS: dict[SignalType, frozenset[SignalType]] = {
    SignalType.CLICK: frozenset({SignalType.IMPRESSION}),
    SignalType.DETAIL_VIEW: frozenset({SignalType.IMPRESSION, SignalType.CLICK}),
    SignalType.PLAY: frozenset({SignalType.IMPRESSION, SignalType.DETAIL_VIEW, SignalType.CLICK}),
    SignalType.QUALIFIED_PLAY: frozenset({SignalType.PLAY}),
    SignalType.PLAYTIME: frozenset({SignalType.PLAY}),
    SignalType.RETURN: frozenset({SignalType.PLAY, SignalType.QUALIFIED_PLAY}),
    SignalType.RETENTION: frozenset({SignalType.PLAY, SignalType.QUALIFIED_PLAY}),
}


class IntegrityDefenses:
    """Evaluate a bounded signal batch and quarantine unsafe ranking inputs."""

    def __init__(self, policy: IntegrityPolicy | None = None) -> None:
        self.policy = policy or IntegrityPolicy()

    def assess(self, signals: Sequence[IntegritySignal]) -> IntegrityAssessment:
        if len(signals) > _MAX_SIGNALS:
            return self._rejected()
        ordered = tuple(sorted(signals, key=lambda item: (item.occurred_at, item.event_digest)))
        flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]] = defaultdict(set)
        self._duplicates(ordered, flagged)
        self._sequence_and_timing(ordered, flagged)
        self._rate_limits(ordered, flagged)
        self._coordinated_bursts(ordered, flagged)
        self._popularity_loops(ordered, flagged)
        evidence = tuple(
            IntegrityEvidence(event_digest=event_digest, code=code, policy_version=self.policy.policy_version, related_digest=related, detail=detail)
            for event_digest in sorted(flagged)
            for code, related, detail in sorted(flagged[event_digest], key=lambda item: (item[0].value, item[1] or "", item[2]))
        )
        flagged_digests = tuple(sorted(flagged))
        unique_digests = tuple(sorted({signal.event_digest for signal in ordered}))
        eligible = tuple(digest for digest in unique_digests if digest not in flagged)
        status = IntegrityStatus.FLAGGED if flagged else IntegrityStatus.CLEAN
        return IntegrityAssessment(
            policy_version=self.policy.policy_version,
            status=status,
            total_signals=len(unique_digests),
            flagged_count=len(flagged_digests),
            ranking_eligible_event_digests=eligible,
            flagged_event_digests=flagged_digests,
            evidence=evidence,
        )

    def assess_raw(self, values: Iterable[object]) -> IntegrityAssessment:
        """Parse untrusted boundary values and fail closed without echoing them."""
        try:
            signals = tuple(IntegritySignal.model_validate(value) for value in values)
        except Exception:
            return self._rejected()
        return self.assess(signals)

    def _rejected(self) -> IntegrityAssessment:
        digest = hashlib.sha256(f"unsafe:{self.policy.policy_version}".encode("ascii")).hexdigest()
        evidence = IntegrityEvidence(
            event_digest=digest,
            code=EvidenceCode.UNSAFE_SIGNAL,
            policy_version=self.policy.policy_version,
            detail="input_rejected",
        )
        return IntegrityAssessment(
            policy_version=self.policy.policy_version,
            status=IntegrityStatus.REJECTED,
            total_signals=0,
            flagged_count=0,
            ranking_eligible_event_digests=(),
            flagged_event_digests=(),
            evidence=(evidence,),
        )

    def _duplicates(self, signals: Sequence[IntegritySignal], flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]]) -> None:
        seen: dict[str, str] = {}
        semantic: dict[str, str] = {}
        for signal in signals:
            prior = seen.get(signal.event_digest)
            if prior is not None:
                flagged[signal.event_digest].add((EvidenceCode.DUPLICATE_EVENT, prior, "replayed_digest"))
                flagged[prior].add((EvidenceCode.DUPLICATE_EVENT, signal.event_digest, "replayed_digest"))
            seen[signal.event_digest] = signal.event_digest
            key = signal.fingerprint()
            prior_semantic = semantic.get(key)
            if prior_semantic is not None and prior_semantic != signal.event_digest:
                flagged[signal.event_digest].add((EvidenceCode.DUPLICATE_SEMANTIC_EVENT, prior_semantic, "same_event_shape"))
                flagged[prior_semantic].add((EvidenceCode.DUPLICATE_SEMANTIC_EVENT, signal.event_digest, "same_event_shape"))
            semantic[key] = signal.event_digest

    def _sequence_and_timing(self, signals: Sequence[IntegritySignal], flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]]) -> None:
        grouped: dict[tuple[str, str], list[IntegritySignal]] = defaultdict(list)
        for signal in signals:
            grouped[(signal.actor_digest, signal.experience_digest)].append(signal)
        for group in grouped.values():
            prior_types: set[SignalType] = set()
            for index, signal in enumerate(group):
                required = _PRIOR_EVENTS.get(signal.signal_type, frozenset())
                if required and not prior_types.intersection(required):
                    flagged[signal.event_digest].add((EvidenceCode.IMPOSSIBLE_SEQUENCE, None, "missing_prior_event"))
                if index and (signal.occurred_at - group[index - 1].occurred_at).total_seconds() < self.policy.min_event_spacing_seconds:
                    flagged[signal.event_digest].add((EvidenceCode.IMPOSSIBLE_TIMING, group[index - 1].event_digest, "events_too_close"))
                prior_types.add(signal.signal_type)

    def _rate_limits(self, signals: Sequence[IntegritySignal], flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]]) -> None:
        self._window_limit(signals, lambda item: item.actor_digest, self.policy.max_actor_events_per_window, EvidenceCode.ACTOR_RATE_LIMIT, "actor_window_limit", flagged)
        self._window_limit(signals, lambda item: item.tenant_digest, self.policy.max_tenant_events_per_window, EvidenceCode.TENANT_RATE_LIMIT, "tenant_window_limit", flagged)

    def _window_limit(
        self,
        signals: Sequence[IntegritySignal],
        key_fn,
        limit: int,
        code: EvidenceCode,
        detail: str,
        flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]],
    ) -> None:
        groups: dict[str, list[IntegritySignal]] = defaultdict(list)
        for signal in signals:
            groups[key_fn(signal)].append(signal)
        window = timedelta(seconds=self.policy.window_seconds)
        for group in groups.values():
            for start, signal in enumerate(group):
                end = start
                while end < len(group) and group[end].occurred_at - signal.occurred_at <= window:
                    end += 1
                if end - start > limit:
                    for item in group[start:end]:
                        flagged[item.event_digest].add((code, None, detail))

    def _coordinated_bursts(self, signals: Sequence[IntegritySignal], flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]]) -> None:
        window = timedelta(seconds=self.policy.window_seconds)
        grouped: dict[str, list[IntegritySignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.experience_digest].append(signal)
        for group in grouped.values():
            for start, signal in enumerate(group):
                burst = [item for item in group if signal.occurred_at <= item.occurred_at <= signal.occurred_at + window]
                actors = {item.actor_digest for item in burst}
                if len(burst) >= self.policy.coordinated_burst_events and len(actors) >= self.policy.coordinated_actor_count:
                    for item in burst:
                        flagged[item.event_digest].add((EvidenceCode.COORDINATED_BURST, signal.experience_digest, "shared_experience_burst"))
                    break

    def _popularity_loops(self, signals: Sequence[IntegritySignal], flagged: dict[str, set[tuple[EvidenceCode, str | None, str]]]) -> None:
        grouped: dict[str, list[IntegritySignal]] = defaultdict(list)
        for signal in signals:
            grouped[signal.experience_digest].append(signal)
        for experience_signals in grouped.values():
            impressions = sum(item.signal_type is SignalType.IMPRESSION for item in experience_signals)
            actions = sum(item.signal_type in _ACTIONS for item in experience_signals)
            if actions < self.policy.min_popularity_actions or impressions == 0 or actions / impressions <= self.policy.max_actions_per_impression:
                continue
            for item in experience_signals:
                if item.signal_type in _ACTIONS:
                    flagged[item.event_digest].add((EvidenceCode.POPULARITY_LOOP, item.experience_digest, "action_impression_ratio"))

def assess_integrity(signals: Sequence[IntegritySignal], *, policy: IntegrityPolicy | None = None) -> IntegrityAssessment:
    """Evaluate signals with the default local integrity policy."""
    return IntegrityDefenses(policy).assess(signals)
