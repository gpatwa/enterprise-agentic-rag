"""Bounded, provider-neutral orchestration of discovery candidate sources."""
from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.candidates.contracts import (
    CandidateSourceResult,
    CandidateTrace,
    Degradation,
    SourceQuota,
)
from app.search.fusion import FusionConfig, HybridFusionResult, fuse_candidates

_MAX_SOURCES = 32
_MAX_CANDIDATES = 1_000
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


class CandidateSource(Protocol):
    """The only operation an orchestrator needs from a candidate source."""

    def retrieve(self, *, tenant_id: str, request_id: str, limit: int) -> CandidateSourceResult:
        """Return a bounded result for one request."""


class SourceSpec(BaseModel):
    """Execution limits and stable identity for one candidate source."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    source_version: str = Field(min_length=1, max_length=64, pattern=_ID)
    timeout_seconds: float = Field(default=0.25, gt=0, le=30, allow_inf_nan=False)
    result_cap: int = Field(default=100, ge=1, le=_MAX_CANDIDATES)
    quota: int = Field(default=20, ge=1, le=_MAX_CANDIDATES)
    required: bool = False


class OrchestrationConfig(BaseModel):
    """Global bounds for one orchestration operation."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    global_limit: int = Field(default=50, ge=1, le=_MAX_CANDIDATES)
    max_workers: int = Field(default=8, ge=1, le=_MAX_SOURCES)
    fusion: FusionConfig = Field(default_factory=FusionConfig)


class CandidateOrchestrationResult(BaseModel):
    """Fused candidates, source health, quotas, and a redacted execution trace."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    fusion: HybridFusionResult
    trace: CandidateTrace
    quotas: tuple[SourceQuota, ...] = Field(max_length=_MAX_SOURCES)


EligibilityCheck = Callable[[str, str], bool]
SourceFactory = Callable[..., CandidateSourceResult]


class CandidateOrchestrator:
    """Run bounded sources concurrently while preserving deterministic output order."""

    def __init__(
        self,
        sources: Mapping[str, SourceFactory],
        specs: Iterable[SourceSpec],
        config: OrchestrationConfig | None = None,
    ) -> None:
        self.config = config or OrchestrationConfig()
        self.specs = tuple(specs)
        if not self.specs or len(self.specs) > _MAX_SOURCES:
            raise ValueError(f"sources must contain between 1 and {_MAX_SOURCES} entries")
        names = tuple(spec.source for spec in self.specs)
        if len(names) != len(set(names)):
            raise ValueError("source specs must be unique")
        if set(sources) != set(names):
            raise ValueError("source implementations must match source specs")
        self.sources = dict(sources)

    def run(
        self,
        *,
        tenant_id: str,
        request_id: str,
        is_eligible: EligibilityCheck | None = None,
    ) -> CandidateOrchestrationResult:
        if not _valid_id(tenant_id) or not _valid_id(request_id):
            raise ValueError("tenant_id and request_id must be valid identifiers")

        results = self._execute_sources(tenant_id=tenant_id, request_id=request_id)
        bounded = tuple(self._apply_quota(result, spec) for result, spec in zip(results, self.specs))
        fusion_config = self.config.fusion.model_copy(update={"limit": self.config.global_limit})
        fusion = fuse_candidates(
            bounded,
            tenant_id=tenant_id,
            request_id=request_id,
            config=fusion_config,
            is_eligible=is_eligible,
        )
        trace = CandidateTrace(
            tenant_digest=_digest(tenant_id),
            request_digest=_digest(request_id),
            source_results=bounded,
        )
        quotas = tuple(
            SourceQuota(source=spec.source, limit=spec.quota, required=spec.required)
            for spec in self.specs
        )
        return CandidateOrchestrationResult(fusion=fusion, trace=trace, quotas=quotas)

    def _execute_sources(self, *, tenant_id: str, request_id: str) -> tuple[CandidateSourceResult, ...]:
        executor = ThreadPoolExecutor(max_workers=min(self.config.max_workers, len(self.specs)))
        futures = [
            executor.submit(
                self.sources[spec.source],
                tenant_id=tenant_id,
                request_id=request_id,
                limit=spec.result_cap,
            )
            for spec in self.specs
        ]
        results: list[CandidateSourceResult] = []
        try:
            for spec, future in zip(self.specs, futures):
                try:
                    result = future.result(timeout=spec.timeout_seconds)
                    results.append(self._validate_result(result, spec, tenant_id, request_id))
                except FutureTimeout:
                    future.cancel()
                    results.append(self._degraded(spec, tenant_id, request_id, Degradation.TIMEOUT, "source_timeout"))
                except Exception:
                    results.append(self._degraded(spec, tenant_id, request_id, Degradation.FAILURE, "source_failure"))
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        return tuple(results)

    @staticmethod
    def _validate_result(
        result: CandidateSourceResult,
        spec: SourceSpec,
        tenant_id: str,
        request_id: str,
    ) -> CandidateSourceResult:
        if result.source != spec.source or result.source_version != spec.source_version:
            raise ValueError("source result identity does not match its specification")
        if result.tenant_id != tenant_id or result.request_id != request_id:
            raise ValueError("source result scope does not match the request")
        return result

    @staticmethod
    def _apply_quota(result: CandidateSourceResult, spec: SourceSpec) -> CandidateSourceResult:
        candidates = result.candidates[: min(spec.result_cap, spec.quota)]
        if result.degradation is not Degradation.OK or candidates == result.candidates:
            return result
        return result.model_copy(update={"candidates": candidates})

    @staticmethod
    def _degraded(
        spec: SourceSpec,
        tenant_id: str,
        request_id: str,
        degradation: Degradation,
        error_code: str,
    ) -> CandidateSourceResult:
        return CandidateSourceResult(
            source=spec.source,
            source_version=spec.source_version,
            tenant_id=tenant_id,
            request_id=request_id,
            degradation=degradation,
            error_code=error_code,
        )


def orchestrate_candidates(
    sources: Mapping[str, SourceFactory],
    specs: Iterable[SourceSpec],
    *,
    tenant_id: str,
    request_id: str,
    config: OrchestrationConfig | None = None,
    is_eligible: EligibilityCheck | None = None,
) -> CandidateOrchestrationResult:
    """Convenience entry point for one bounded orchestration request."""
    return CandidateOrchestrator(sources, specs, config).run(
        tenant_id=tenant_id,
        request_id=request_id,
        is_eligible=is_eligible,
    )


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _valid_id(value: str) -> bool:
    import re

    return bool(re.fullmatch(_ID, value))
