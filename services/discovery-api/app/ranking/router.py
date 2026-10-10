"""Closed-world routing across the bounded online ranking stages."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from enum import Enum
from time import monotonic
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_TOKEN = r"^[a-z][a-z0-9_.:-]{0,63}$"
_MAX_CANDIDATES = 500
_MAX_STAGES = 4
_MAX_REASONS = 8


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class RankingMode(str, Enum):
    HYBRID_ONLY = "hybrid_only"
    PRE_RANK = "pre_rank"
    LEARNED_RANK = "learned_rank"
    FULL_RANK = "full_rank"


class StageName(str, Enum):
    HYBRID = "hybrid"
    PRE_RANK = "pre_rank"
    LEARNED_RANK = "learned_rank"
    FULL_RANK = "full_rank"


class FallbackReason(str, Enum):
    NONE = "none"
    STAGE_DISABLED = "stage_disabled"
    STAGE_UNKNOWN = "stage_unknown"
    STAGE_FAILED = "stage_failed"
    STAGE_TIMEOUT = "stage_timeout"
    STAGE_OUTPUT_INVALID = "stage_output_invalid"
    ELIGIBILITY_RECHECK = "eligibility_recheck"


class RouterCandidate(_FrozenModel):
    """Minimal public candidate envelope; private features never cross this API."""

    candidate_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    score: float = Field(default=0, ge=0, le=1, allow_inf_nan=False)
    original_rank: int = Field(default=1, ge=1, le=_MAX_CANDIDATES)
    eligible: bool = True
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)

    @model_validator(mode="after")
    def validate_reasons(self) -> "RouterCandidate":
        if any(not reason or len(reason) > 64 for reason in self.reason_codes):
            raise ValueError("reason codes must be bounded")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        return self


class StageConfig(_FrozenModel):
    stage: StageName
    enabled: bool = True
    cap: int = Field(default=_MAX_CANDIDATES, ge=1, le=_MAX_CANDIDATES)
    timeout_ms: int = Field(default=100, ge=1, le=2_000)
    component_version: str = Field(default="component-v1", min_length=1, max_length=128, pattern=_VERSION)
    model_version: str = Field(default="model-v1", min_length=1, max_length=128, pattern=_VERSION)
    policy_version: str = Field(default="policy-v1", min_length=1, max_length=128, pattern=_VERSION)


class StageOutput(_FrozenModel):
    """A stage may reorder or remove candidates, but may never add one."""

    candidates: tuple[RouterCandidate, ...] = Field(max_length=_MAX_CANDIDATES)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)

    @model_validator(mode="after")
    def validate_reasons(self) -> "StageOutput":
        if any(not reason or len(reason) > 64 for reason in self.reason_codes):
            raise ValueError("reason codes must be bounded")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        return self


class StageDecision(_FrozenModel):
    """Immutable, redacted audit evidence for one attempted stage."""

    stage: StageName
    attempted: bool
    applied: bool
    fallback_reason: FallbackReason
    input_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    output_count: int = Field(ge=0, le=_MAX_CANDIDATES)
    latency_ms: int = Field(ge=0, le=2_000)
    component_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    policy_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    reason_codes: tuple[str, ...] = Field(default_factory=tuple, max_length=_MAX_REASONS)


class StageRouterRequest(_FrozenModel):
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    mode: RankingMode
    candidates: tuple[RouterCandidate, ...] = Field(min_length=1, max_length=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_candidates(self) -> "StageRouterRequest":
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        return self


class StageRouterResult(_FrozenModel):
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    mode: RankingMode
    candidates: tuple[RouterCandidate, ...] = Field(max_length=_MAX_CANDIDATES)
    trace: tuple[StageDecision, ...] = Field(max_length=_MAX_STAGES)
    fallback: bool

    @model_validator(mode="after")
    def validate_result(self) -> "StageRouterResult":
        ids = tuple(candidate.candidate_id for candidate in self.candidates)
        if len(ids) != len(set(ids)) or any(not candidate.eligible for candidate in self.candidates):
            raise ValueError("router output must contain unique eligible candidates")
        if len(self.trace) > _MAX_STAGES:
            raise ValueError("router trace exceeds bound")
        return self


class RankingStage(Protocol):
    def __call__(self, candidates: tuple[RouterCandidate, ...]) -> StageOutput: ...


_MODE_STAGES = {
    RankingMode.HYBRID_ONLY: (StageName.HYBRID,),
    RankingMode.PRE_RANK: (StageName.HYBRID, StageName.PRE_RANK),
    RankingMode.LEARNED_RANK: (StageName.HYBRID, StageName.PRE_RANK, StageName.LEARNED_RANK),
    RankingMode.FULL_RANK: (StageName.HYBRID, StageName.PRE_RANK, StageName.LEARNED_RANK, StageName.FULL_RANK),
}


class RankingStageRouter:
    """Run a selected stage chain with deterministic closed-world fallbacks."""

    def __init__(self, stages: dict[StageName, RankingStage] | None = None, configs: tuple[StageConfig, ...] | None = None) -> None:
        self.stages = dict(stages or {})
        config_values = configs or tuple(StageConfig(stage=stage) for stage in StageName)
        if len({config.stage for config in config_values}) != len(config_values):
            raise ValueError("stage configurations must be unique")
        self.configs = {config.stage: config for config in config_values}

    def route(self, request: StageRouterRequest) -> StageRouterResult:
        current = tuple(candidate for candidate in request.candidates if candidate.eligible)
        trace: list[StageDecision] = []
        for stage in _MODE_STAGES[request.mode]:
            config = self.configs.get(stage)
            if config is None:
                trace.append(self._decision(stage, False, False, FallbackReason.STAGE_UNKNOWN, len(current), len(current)))
                continue
            before = current
            if not config.enabled:
                trace.append(self._decision(stage, True, False, FallbackReason.STAGE_DISABLED, len(before), len(before), config=config))
                continue
            handler = self.stages.get(stage)
            if handler is None:
                trace.append(self._decision(stage, True, False, FallbackReason.STAGE_UNKNOWN, len(before), len(before), config=config))
                continue
            started = monotonic()
            output, reason = self._invoke(handler, before[: config.cap], config.timeout_ms)
            if output is None:
                trace.append(self._decision(stage, True, False, reason, len(before), len(before), config=config, started=started))
                continue
            allowed = {candidate.candidate_id for candidate in before}
            output_ids = tuple(candidate.candidate_id for candidate in output.candidates)
            if len(output_ids) != len(set(output_ids)) or any(candidate.candidate_id not in allowed or not candidate.eligible for candidate in output.candidates):
                trace.append(self._decision(stage, True, False, FallbackReason.STAGE_OUTPUT_INVALID, len(before), len(before), config=config, started=started))
                continue
            current = output.candidates[: config.cap]
            trace.append(self._decision(stage, True, True, FallbackReason.NONE, len(before), len(current), config=config, started=started, reasons=output.reason_codes))
        return StageRouterResult(
            request_id=request.request_id,
            mode=request.mode,
            candidates=current,
            trace=tuple(trace),
            fallback=any(decision.fallback_reason is not FallbackReason.NONE for decision in trace),
        )

    @staticmethod
    def _invoke(handler: RankingStage, candidates: tuple[RouterCandidate, ...], timeout_ms: int) -> tuple[StageOutput | None, FallbackReason]:
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(handler, candidates)
        try:
            result = future.result(timeout=timeout_ms / 1000)
            if not isinstance(result, StageOutput):
                return None, FallbackReason.STAGE_OUTPUT_INVALID
            return result, FallbackReason.NONE
        except FutureTimeout:
            future.cancel()
            return None, FallbackReason.STAGE_TIMEOUT
        except Exception:
            return None, FallbackReason.STAGE_FAILED
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    @staticmethod
    def _decision(stage: StageName, attempted: bool, applied: bool, reason: FallbackReason, input_count: int, output_count: int, *, config: StageConfig | None = None, started: float | None = None, reasons: tuple[str, ...] = ()) -> StageDecision:
        config = config or StageConfig(stage=stage)
        elapsed = 0 if started is None else min(2_000, max(0, int((monotonic() - started) * 1000)))
        return StageDecision(
            stage=stage,
            attempted=attempted,
            applied=applied,
            fallback_reason=reason,
            input_count=input_count,
            output_count=output_count,
            latency_ms=elapsed,
            component_version=config.component_version,
            model_version=config.model_version,
            policy_version=config.policy_version,
            reason_codes=tuple(dict.fromkeys((*reasons, reason.value) if reason is not FallbackReason.NONE else reasons))[:_MAX_REASONS],
        )


__all__ = [
    "FallbackReason",
    "RankingMode",
    "RankingStageRouter",
    "RankingStage",
    "RouterCandidate",
    "StageConfig",
    "StageDecision",
    "StageName",
    "StageOutput",
    "StageRouterRequest",
    "StageRouterResult",
]
