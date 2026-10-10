"""Bounded, redacted contracts for independently degradable candidate sources."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = Field(min_length=1, max_length=64, pattern=_ID)


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class Degradation(str, Enum):
    OK = "ok"
    EMPTY = "empty"
    TIMEOUT = "timeout"
    FAILURE = "failure"


class SourceQuota(_Contract):
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    limit: int = Field(ge=1, le=1000)
    required: bool = False


class Candidate(_Contract):
    experience_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    source_version: str = _VERSION
    score: float = Field(ge=0, le=1, allow_inf_nan=False)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)
    eligibility_code: Literal["eligible"] = "eligible"

    @model_validator(mode="after")
    def validate_reasons(self) -> "Candidate":
        if any(not reason.strip() for reason in self.reason_codes):
            raise ValueError("reason codes must be non-empty")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        return self


class CandidateSourceResult(_Contract):
    source: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_.:-]+$")
    source_version: str = _VERSION
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    candidates: tuple[Candidate, ...] = Field(default_factory=tuple, max_length=1000)
    degradation: Degradation = Degradation.OK
    error_code: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_.:-]+$")

    @model_validator(mode="after")
    def validate_result(self) -> "CandidateSourceResult":
        if any(candidate.tenant_id != self.tenant_id or candidate.source != self.source for candidate in self.candidates):
            raise ValueError("candidate scope or source does not match result")
        if any(candidate.source_version != self.source_version for candidate in self.candidates):
            raise ValueError("candidate version does not match result")
        ids = [candidate.experience_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate IDs must be unique")
        if self.degradation is Degradation.OK and self.error_code is not None:
            raise ValueError("successful result cannot carry an error")
        if self.degradation in {Degradation.FAILURE, Degradation.TIMEOUT} and not self.error_code:
            raise ValueError("degraded result requires an error code")
        if self.degradation is Degradation.EMPTY and self.candidates:
            raise ValueError("empty result cannot contain candidates")
        return self


class CandidateBatch(_Contract):
    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    request_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    candidates: tuple[Candidate, ...] = Field(default_factory=tuple, max_length=1000)
    quotas: tuple[SourceQuota, ...] = Field(default_factory=tuple, max_length=64)

    @model_validator(mode="after")
    def validate_batch(self) -> "CandidateBatch":
        if any(candidate.tenant_id != self.tenant_id for candidate in self.candidates):
            raise ValueError("candidate tenant does not match batch")
        ids = [candidate.experience_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("batch candidate IDs must be unique")
        sources = [quota.source for quota in self.quotas]
        if len(sources) != len(set(sources)):
            raise ValueError("source quotas must be unique")
        return self


class CandidateTrace(_Contract):
    tenant_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_results: tuple[CandidateSourceResult, ...] = Field(max_length=64)

    @model_validator(mode="after")
    def validate_source_identity(self) -> "CandidateTrace":
        names = [result.source for result in self.source_results]
        if len(names) != len(set(names)):
            raise ValueError("trace sources must be unique")
        return self
