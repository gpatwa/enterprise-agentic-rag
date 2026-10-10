"""Bounded local online ranker inference with a closed-world fallback."""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from math import isfinite
from time import monotonic
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ranking.contracts import RankingContext
from app.ranking.pre_rank import PreRankCandidate
from app.ranking.registry import ModelRegistry

_MAX_CANDIDATES = 500
_MAX_FEATURES = 512
_MAX_ATTEMPTS = 3
_MAX_TIMEOUT_MS = 2_000
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"


class _InferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class RankerModel(Protocol):
    """A local model adapter; it returns scores only for supplied candidates."""

    def predict(self, context: RankingContext, candidates: tuple[PreRankCandidate, ...]) -> Mapping[str, float]: ...


class RankerInferenceRequest(_InferenceModel):
    """Explicit, versioned input envelope for one online ranking call."""

    candidate_batch_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    model_name: str = Field(min_length=1, max_length=128, pattern=_ID)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    feature_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    ranking_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    context: RankingContext
    candidates: tuple[PreRankCandidate, ...] = Field(min_length=1, max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_request(self) -> "RankerInferenceRequest":
        if self.context.ranking_version != self.ranking_version:
            raise ValueError("ranking version does not match context")
        if self.context.context.feature_version != self.feature_version:
            raise ValueError("feature version does not match context")
        if any(candidate.candidate_id not in {item.subject_id for item in self.context.candidates} for candidate in self.candidates):
            raise ValueError("candidate is outside supplied context")
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(set(ids)) != len(ids):
            raise ValueError("candidate IDs must be unique")
        feature_sets = (self.context.context, *self.context.candidates)
        if self.context.user is not None:
            feature_sets = (self.context.user, *feature_sets)
        feature_count = sum(len(feature_set.features) for feature_set in feature_sets)
        if feature_count > _MAX_FEATURES:
            raise ValueError("feature batch exceeds bound")
        if any(not candidate.eligible for candidate in self.candidates):
            raise ValueError("inference accepts eligible candidates only")
        return self


class RankedCandidate(_InferenceModel):
    """A scored candidate whose provenance and eligibility are closed-world."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    original_rank: int = Field(ge=1, le=_MAX_CANDIDATES)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    evidence: tuple[str, ...] = Field(default_factory=tuple, max_length=8)
    eligible: bool = True


class RankerInferenceResult(_InferenceModel):
    """Bounded online output with an observable but redacted fallback reason."""

    candidate_batch_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    model_name: str = Field(min_length=1, max_length=128, pattern=_ID)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    ranking_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    items: tuple[RankedCandidate, ...] = Field(max_length=_MAX_CANDIDATES)
    fallback: bool
    fallback_reason: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    latency_ms: int = Field(ge=0, le=_MAX_TIMEOUT_MS)

    @model_validator(mode="after")
    def validate_fallback(self) -> "RankerInferenceResult":
        if self.fallback != (self.fallback_reason is not None):
            raise ValueError("fallback reason must match fallback state")
        ids = tuple(item.candidate_id for item in self.items)
        if len(ids) != len(set(ids)):
            raise ValueError("result candidate IDs must be unique")
        if any(not item.eligible for item in self.items):
            raise ValueError("inference output cannot mutate eligibility")
        return self


class BoundedRankerInference:
    """Run an approved local model, falling back without expanding the batch."""

    def __init__(
        self,
        registry: ModelRegistry,
        models: Mapping[tuple[str, str], RankerModel],
        *,
        timeout_ms: int = 100,
        max_attempts: int = 1,
        limit: int = _MAX_CANDIDATES,
    ) -> None:
        if not 1 <= timeout_ms <= _MAX_TIMEOUT_MS:
            raise ValueError("timeout_ms is outside bound")
        if not 1 <= max_attempts <= _MAX_ATTEMPTS:
            raise ValueError("max_attempts is outside bound")
        if not 1 <= limit <= _MAX_CANDIDATES:
            raise ValueError("limit is outside bound")
        self.registry = registry
        self.models = dict(models)
        self.timeout_ms = timeout_ms
        self.max_attempts = max_attempts
        self.limit = limit

    def rank(self, request: RankerInferenceRequest) -> RankerInferenceResult:
        started = monotonic()
        candidates = request.candidates[: self.limit]
        reason = self._compatibility_reason(request)
        scores: Mapping[str, float] | None = None
        if reason is None:
            model = self.models.get((request.model_name, request.model_version))
            if model is None:
                reason = "model_missing"
            else:
                scores, reason = self._predict(model, request, candidates)
        if scores is None:
            items = self._fallback(candidates, reason or "model_failure")
            fallback = True
            fallback_reason = reason or "model_failure"
        else:
            items = self._rank(candidates, scores)
            fallback = False
            fallback_reason = None
        elapsed = min(_MAX_TIMEOUT_MS, max(0, int((monotonic() - started) * 1000)))
        return RankerInferenceResult(
            candidate_batch_id=request.candidate_batch_id,
            model_name=request.model_name,
            model_version=request.model_version,
            ranking_version=request.ranking_version,
            items=items,
            fallback=fallback,
            fallback_reason=fallback_reason,
            latency_ms=elapsed,
        )

    def _compatibility_reason(self, request: RankerInferenceRequest) -> str | None:
        try:
            record = self.registry.active(request.model_name)
        except LookupError:
            return "model_unapproved"
        compatibility = record.compatibility
        if record.model_version != request.model_version:
            return "model_incompatible"
        if compatibility.feature_version != request.feature_version:
            return "feature_incompatible"
        if compatibility.policy_version != request.policy_version:
            return "policy_incompatible"
        if compatibility.ranking_version != request.ranking_version:
            return "ranking_incompatible"
        return None

    def _predict(
        self, model: RankerModel, request: RankerInferenceRequest, candidates: tuple[PreRankCandidate, ...]
    ) -> tuple[Mapping[str, float] | None, str | None]:
        timeout = self.timeout_ms / 1000
        for _ in range(self.max_attempts):
            try:
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(model.predict, request.context, candidates)
                    scores = future.result(timeout=timeout)
                if not isinstance(scores, Mapping) or set(scores) != {candidate.candidate_id for candidate in candidates}:
                    return None, "score_batch_invalid"
                if any(not isinstance(value, (int, float)) or not isfinite(value) or not 0 <= value <= 1 for value in scores.values()):
                    return None, "score_range_invalid"
                return scores, None
            except FutureTimeout:
                continue
            except Exception:  # Provider/model details must not enter response evidence.
                return None, "model_failure"
        return None, "model_timeout"

    @staticmethod
    def _rank(candidates: tuple[PreRankCandidate, ...], scores: Mapping[str, float]) -> tuple[RankedCandidate, ...]:
        ordered = sorted(candidates, key=lambda item: (-float(scores[item.candidate_id]), item.original_rank, item.candidate_id))
        return tuple(
            RankedCandidate(
                candidate_id=item.candidate_id,
                source=item.source,
                score=float(scores[item.candidate_id]),
                original_rank=item.original_rank,
                reason_codes=item.reason_codes,
                evidence=item.evidence,
            )
            for item in ordered
        )

    @staticmethod
    def _fallback(candidates: Sequence[PreRankCandidate], reason: str) -> tuple[RankedCandidate, ...]:
        ordered = sorted(candidates, key=lambda item: (-item.base_score, item.original_rank, item.candidate_id))
        return tuple(
            RankedCandidate(
                candidate_id=item.candidate_id,
                source=item.source,
                score=item.base_score,
                original_rank=item.original_rank,
                reason_codes=tuple(dict.fromkeys((*item.reason_codes, "ranker_fallback"))),
                evidence=item.evidence,
            )
            for item in ordered
        )


__all__ = [
    "BoundedRankerInference",
    "RankerInferenceRequest",
    "RankerInferenceResult",
    "RankerModel",
    "RankedCandidate",
]
