"""Deterministic fusion of independently degradable candidate sources."""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.candidates.contracts import CandidateSourceResult, Degradation

_MAX_SOURCES = 32
_MAX_CANDIDATES = 1000
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class FusionMethod(str, Enum):
    RRF = "rrf"
    WEIGHTED = "weighted"


class FusionConfig(BaseModel):
    """Bounded, explicit parameters for one fusion operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    method: FusionMethod = FusionMethod.RRF
    rrf_k: int = Field(default=60, ge=1, le=1000)
    limit: int = Field(default=50, ge=1, le=_MAX_CANDIDATES)
    source_weights: Mapping[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_weights(self) -> "FusionConfig":
        for source, weight in self.source_weights.items():
            if not source or not source.islower() or any(
                character not in "abcdefghijklmnopqrstuvwxyz0123456789_.:-"
                for character in source
            ):
                raise ValueError("source weights must use lowercase source names")
            if weight < 0 or weight > 100:
                raise ValueError("source weights must be between 0 and 100")
        if self.method is FusionMethod.WEIGHTED and not self.source_weights:
            raise ValueError("weighted fusion requires source weights")
        return self


class SourceEvidence(BaseModel):
    """Redacted evidence retained for a fused candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    rank: int = Field(ge=1, le=_MAX_CANDIDATES)
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)


class FusedCandidate(BaseModel):
    """One deduplicated candidate with all contributing source evidence."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    score: float = Field(ge=0, allow_inf_nan=False)
    source_evidence: tuple[SourceEvidence, ...] = Field(min_length=1, max_length=_MAX_SOURCES)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=32)
    eligibility_code: Literal["eligible"] = "eligible"


class HybridFusionResult(BaseModel):
    """Fused candidates plus source health for downstream ranking and audit."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    candidates: tuple[FusedCandidate, ...] = Field(max_length=_MAX_CANDIDATES)
    source_results: tuple[CandidateSourceResult, ...] = Field(max_length=_MAX_SOURCES)
    degraded_sources: tuple[str, ...] = Field(max_length=_MAX_SOURCES)


EligibilityCheck = Callable[[str, str], bool]


class HybridFusion:
    """Fuse candidate sources without contacting a search provider."""

    def fuse(
        self,
        source_results: Iterable[CandidateSourceResult],
        *,
        tenant_id: str,
        request_id: str,
        config: FusionConfig | None = None,
        expected_source_versions: Mapping[str, str] | None = None,
        is_eligible: EligibilityCheck | None = None,
    ) -> HybridFusionResult:
        fusion_config = config or FusionConfig()
        results = tuple(source_results)
        if len(results) > _MAX_SOURCES:
            raise ValueError(f"source results cannot exceed {_MAX_SOURCES}")
        names = tuple(result.source for result in results)
        if len(names) != len(set(names)):
            raise ValueError("source results must have unique source names")

        expected = expected_source_versions or {}
        contributions: dict[str, list[SourceEvidence]] = {}
        for result in results:
            if result.tenant_id != tenant_id or result.request_id != request_id:
                raise ValueError("source result scope does not match fusion request")
            if result.source in expected and result.source_version != expected[result.source]:
                raise ValueError(f"source version does not match for {result.source}")
            if result.degradation in {Degradation.TIMEOUT, Degradation.FAILURE}:
                continue
            for rank, candidate in enumerate(result.candidates, start=1):
                if is_eligible is not None and not is_eligible(candidate.experience_id, tenant_id):
                    continue
                contributions.setdefault(candidate.experience_id, []).append(
                    SourceEvidence(
                        source=result.source,
                        rank=rank,
                        score=candidate.score,
                        reason_codes=candidate.reason_codes,
                    )
                )

        fused: list[FusedCandidate] = []
        for experience_id, evidence in contributions.items():
            score = self._score(evidence, fusion_config)
            reasons = tuple(
                dict.fromkeys(
                    reason
                    for item in evidence
                    for reason in (f"{item.source}:{code}" for code in item.reason_codes)
                )
            )
            fused.append(
                FusedCandidate(
                    experience_id=experience_id,
                    tenant_id=tenant_id,
                    score=score,
                    source_evidence=tuple(sorted(evidence, key=lambda item: item.source)),
                    reason_codes=reasons,
                )
            )
        fused.sort(key=lambda candidate: (-candidate.score, candidate.experience_id))

        degraded = tuple(
            result.source
            for result in results
            if result.degradation is not Degradation.OK
        )
        return HybridFusionResult(
            tenant_id=tenant_id,
            request_id=request_id,
            candidates=tuple(fused[: fusion_config.limit]),
            source_results=results,
            degraded_sources=degraded,
        )

    @staticmethod
    def _score(evidence: list[SourceEvidence], config: FusionConfig) -> float:
        if config.method is FusionMethod.RRF:
            return round(sum(1.0 / (config.rrf_k + item.rank) for item in evidence), 8)
        return round(
            sum(
                item.score * config.source_weights.get(item.source, 0.0)
                for item in evidence
            ),
            8,
        )


def fuse_candidates(
    source_results: Iterable[CandidateSourceResult],
    *,
    tenant_id: str,
    request_id: str,
    config: FusionConfig | None = None,
    expected_source_versions: Mapping[str, str] | None = None,
    is_eligible: EligibilityCheck | None = None,
) -> HybridFusionResult:
    """Convenience entry point for deterministic hybrid fusion."""
    return HybridFusion().fuse(
        source_results,
        tenant_id=tenant_id,
        request_id=request_id,
        config=config,
        expected_source_versions=expected_source_versions,
        is_eligible=is_eligible,
    )
