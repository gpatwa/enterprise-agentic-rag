"""Drift observations, alert rules, and alerts for the governed analytics runtime (ADS-058).

Monitors are advisory and read-only: they compare a current window of terminal runs with a baseline window
and raise an alert that points at a runbook. They never change a run, a release, a pointer, or a threshold,
and an alert starts no rollback. The alert thresholds are a policy a person must approve.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.agent_runtime import TerminalKind

DRIFT_VERSION = "v1"
MonitorKind = Literal["context", "retrieval", "intent", "outcomes", "latency", "cost"]
Statistic = Literal[
    "stale_context_rate",
    "max_context_age_hours",
    "empty_retrieval_rate",
    "mean_context_items",
    "malformed_intent_rate",
    "clarification_rate",
    "outcome_distribution_tvd",
    "success_rate",
    "p95_latency_ms",
    "mean_cost_units",
]
# How the current value is compared with the baseline value:
#   abs_increase / abs_decrease: current - baseline (or baseline - current) >= threshold
#   rel_decrease: (baseline - current) / baseline >= threshold
#   ratio: current / baseline >= threshold
#   value: current >= threshold (the baseline is not used)
Comparison = Literal["abs_increase", "abs_decrease", "rel_decrease", "ratio", "value"]
Severity = Literal["warning", "critical"]
_COMPARISON_STATISTICS: dict[str, set[str]] = {}


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RunObservation(_Frozen):
    """What a monitor may know about one terminal run: counts, codes, and numbers, never content."""

    run_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    observed_at: datetime
    outcome: TerminalKind
    error_codes: tuple[str, ...] = ()
    context_items: int | None = Field(default=None, ge=0)
    context_age_hours: float | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    cost_units: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def aware(self) -> "RunObservation":
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class DriftRule(_Frozen):
    rule_id: str = Field(pattern=r"^[A-Z]-\d{2}$")
    monitor: MonitorKind
    statistic: Statistic
    comparison: Comparison
    threshold: float = Field(gt=0)
    severity: Severity
    runbook_id: str = Field(pattern=r"^drift-[a-z]+$")
    min_samples: int = Field(ge=1, le=100_000)


class DriftApproval(_Frozen):
    status: Literal["proposed", "approved"]
    approved_by: str | None = None
    approved_at: str | None = None
    note: str | None = None


class DriftPolicy(_Frozen):
    policy_version: str = Field(min_length=1, max_length=64)
    rules: tuple[DriftRule, ...] = Field(min_length=1)
    approval: DriftApproval

    @model_validator(mode="after")
    def sane(self) -> "DriftPolicy":
        ids = [rule.rule_id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("drift rule IDs must be unique")
        if self.approval.status == "approved" and not (self.approval.approved_by and self.approval.approved_at):
            raise ValueError("an approved policy records who approved it and when")
        for rule in self.rules:
            if rule.runbook_id != f"drift-{rule.monitor}":
                raise ValueError(f"rule {rule.rule_id} must point at the {rule.monitor} runbook")
        return self


class DriftAlert(_Frozen):
    rule_id: str
    monitor: MonitorKind
    statistic: Statistic
    severity: Severity
    runbook_id: str
    baseline_value: float | None
    current_value: float
    threshold: float
    comparison: Comparison
    baseline_samples: int = Field(ge=0)
    current_samples: int = Field(ge=0)


class SkippedRule(_Frozen):
    rule_id: str
    reason: Literal["insufficient_data", "baseline_zero", "no_data"]
    baseline_samples: int = Field(ge=0)
    current_samples: int = Field(ge=0)


class DriftReport(_Frozen):
    drift_version: Literal["v1"] = DRIFT_VERSION
    policy_version: str
    policy_status: Literal["proposed", "approved"]
    baseline_samples: int = Field(ge=0)
    current_samples: int = Field(ge=0)
    alerts: tuple[DriftAlert, ...] = ()
    skipped: tuple[SkippedRule, ...] = ()
