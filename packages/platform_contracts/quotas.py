"""Per-tenant quotas, SLO objectives, and the alerts they raise (ADS-066).

Quotas protect the platform and the other tenants: a request rate, a concurrency cap, and a daily cost budget per tenant. The
SLO objective turns the user-visible outcomes into an error budget with burn-rate alerts. These are operating limits chosen
without production data, so the shipped policy is *proposed*; the manager enforces whatever policy it is given.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TenantQuota(_Frozen):
    requests_per_minute: float = Field(gt=0, le=100_000)
    burst: int = Field(ge=1, le=10_000)
    max_concurrent_runs: int = Field(ge=1, le=1_000)
    daily_cost_units: float = Field(gt=0)
    warn_fraction: float = Field(default=0.8, gt=0, lt=1)


class SloObjective(_Frozen):
    success_target: float = Field(gt=0, lt=1)  # share of requests that must not be a system failure
    p95_latency_seconds: float = Field(gt=0)
    fast_window_seconds: int = Field(default=300, ge=1)
    slow_window_seconds: int = Field(default=3600, ge=1)
    fast_burn_rate: float = Field(
        default=14.4, gt=1
    )  # budget burning this many times too fast over the fast window: page
    slow_burn_rate: float = Field(default=6.0, gt=1)  # ... over the slow window: ticket
    min_requests: int = Field(default=20, ge=1)  # too little traffic is not an alert

    @model_validator(mode="after")
    def windows(self) -> "SloObjective":
        if self.fast_window_seconds >= self.slow_window_seconds:
            raise ValueError("the fast window must be shorter than the slow window")
        return self


class QuotaApproval(_Frozen):
    status: Literal["proposed", "approved"]
    approved_by: str | None = None
    approved_at: str | None = None
    note: str | None = None


class QuotaPolicy(_Frozen):
    policy_version: str = Field(min_length=1, max_length=64)
    default: TenantQuota
    tenants: dict[str, TenantQuota] = Field(default_factory=dict, max_length=10_000)
    slo: SloObjective
    approval: QuotaApproval

    @model_validator(mode="after")
    def sane(self) -> "QuotaPolicy":
        if self.approval.status == "approved" and not (self.approval.approved_by and self.approval.approved_at):
            raise ValueError("an approved policy records who approved it and when")
        return self

    def quota_for(self, tenant_id: str) -> TenantQuota:
        return self.tenants.get(tenant_id, self.default)


AlertKind = Literal[
    "cost_budget_warning",
    "cost_budget_exhausted",
    "rate_limited",
    "concurrency_limited",
    "slo_fast_burn",
    "slo_slow_burn",
    "slo_latency",
]


class OpsAlert(_Frozen):
    kind: AlertKind
    severity: Literal["warning", "page"]
    tenant_id: str
    value: float
    threshold: float
    runbook_id: str = Field(pattern=r"^ops-[a-z-]+$")
