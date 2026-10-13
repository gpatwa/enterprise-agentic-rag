"""Shadow, canary, promotion, and rollback of an approved prompt candidate (ADS-057).

A rollout is an append-only event log bound to one candidate at one content fingerprint. Promotion only
creates the next released registry version and moves an *active-version pointer*; nothing in the runtime
reads either yet. Rollback only appends (a reverted pointer and an event): no evidence, run, or released
version is ever deleted. The policy that sets the pass/fail criteria must itself be approved.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ROLLOUT_VERSION = "v1"
_HEX64 = r"^[0-9a-f]{64}$"
RolloutState = Literal["evaluated", "shadow", "canary", "promoted", "rolled_back"]
EventType = Literal["started", "shadow_passed", "canary_passed", "promoted", "monitor_ok", "rolled_back"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PolicyApproval(_Frozen):
    status: Literal["proposed", "approved"]
    approved_by: str | None = None
    approved_at: str | None = None
    note: str | None = None


class RolloutPolicy(_Frozen):
    """The pass/fail criteria of a rollout. A rollout runs only under an approved policy."""

    policy_version: str = Field(min_length=1, max_length=64)
    shadow_min_agreement: float = Field(ge=0.0, le=1.0)
    canary_fractions: tuple[float, ...] = Field(min_length=1, max_length=5)
    canary_max_error_rate: float = Field(ge=0.0, le=1.0)
    monitor_max_error_rate: float = Field(ge=0.0, le=1.0)
    approval_max_age_hours: int = Field(ge=1, le=24 * 365)
    approval: PolicyApproval

    @model_validator(mode="after")
    def sane(self) -> "RolloutPolicy":
        fractions = list(self.canary_fractions)
        if fractions != sorted(set(fractions)) or not all(0 < f <= 1 for f in fractions):
            raise ValueError("canary fractions are strictly increasing values in (0, 1]")
        if self.approval.status == "approved" and not (self.approval.approved_by and self.approval.approved_at):
            raise ValueError("an approved policy records who approved it and when")
        return self


class RolloutRecord(_Frozen):
    rollout_version: Literal["v1"] = ROLLOUT_VERSION
    rollout_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    purpose: str = Field(min_length=1, max_length=255)
    subject_kind: Literal["prompt_candidate"] = "prompt_candidate"
    subject_id: str = Field(min_length=1, max_length=255)
    subject_fingerprint: str = Field(pattern=_HEX64)
    prompt_name: str = Field(min_length=1, max_length=64)
    baseline_version: str = Field(min_length=1, max_length=64)
    review_id: str = Field(min_length=1, max_length=255)
    evaluation_id: str = Field(min_length=1, max_length=255)
    policy_version: str = Field(min_length=1, max_length=64)
    policy_fingerprint: str = Field(pattern=_HEX64)
    started_by: str = Field(min_length=1, max_length=255)
    created_at: datetime


class RolloutEvent(_Frozen):
    seq: int = Field(ge=1)
    event_type: EventType
    actor: str = Field(min_length=1, max_length=255)
    detail: dict[str, str | int | float] = Field(default_factory=dict)
    created_at: datetime


class ReleasePointer(_Frozen):
    """Which released version a consumer *would* use. Append-only; nothing reads it at runtime yet."""

    prompt_name: str
    seq: int = Field(ge=1)
    version: str
    rollout_id: str | None
    reason: str
    set_at: datetime


class RolloutStatus(_Frozen):
    record: RolloutRecord
    state: RolloutState
    events: tuple[RolloutEvent, ...] = ()
    canary_passed: tuple[float, ...] = ()
    released_version: str | None = None
    rollback_reason: str | None = None
