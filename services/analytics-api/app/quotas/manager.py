"""Per-tenant admission, cost attribution, SLO tracking, and alerts (ADS-066).

Everything is deterministic under an injected clock and holds only counts, durations, and cost units per tenant: no request text,
rows, SQL, or user identifiers. A tenant exhausting its own quota can never consume another tenant's: every limit is keyed by tenant.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from packages.platform_contracts.quotas import OpsAlert, QuotaPolicy, TenantQuota

Clock = Callable[[], datetime]
RATE_LIMITED, CONCURRENCY_LIMITED, COST_EXHAUSTED = "rate_limited", "concurrency_limited", "cost_budget_exhausted"


@dataclass(frozen=True)
class Admission:
    allowed: bool
    code: str | None = None
    retry_after_seconds: float | None = None


@dataclass
class _Bucket:
    tokens: float
    updated: datetime


@dataclass
class TenantUsage:
    in_flight: int = 0
    day: str = ""
    day_cost_units: float = 0.0
    rate_limited: int = 0
    admitted: int = 0
    by_purpose: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_dialect: dict[str, float] = field(default_factory=lambda: defaultdict(float))


class QuotaManager:
    def __init__(self, policy: QuotaPolicy, *, clock: Clock = lambda: datetime.now(timezone.utc)) -> None:
        self.policy, self._clock = policy, clock
        self._lock = threading.Lock()
        self._buckets: dict[str, _Bucket] = {}
        self._usage: dict[str, TenantUsage] = defaultdict(TenantUsage)
        self._recorded: set[tuple[str, str]] = set()
        self.alerts: list[OpsAlert] = []
        self._alerted: set[tuple[str, str, str]] = set()

    # ---- admission ----

    def admit(self, tenant_id: str) -> Admission:
        quota, now = self.policy.quota_for(tenant_id), self._clock()
        with self._lock:
            usage = self._roll(tenant_id, now)
            if usage.day_cost_units >= quota.daily_cost_units:
                self._alert(
                    "cost_budget_exhausted",
                    "page",
                    tenant_id,
                    usage.day_cost_units,
                    quota.daily_cost_units,
                    "ops-cost-budget",
                )
                return Admission(False, COST_EXHAUSTED, self._seconds_to_midnight(now))
            if usage.in_flight >= quota.max_concurrent_runs:
                usage.rate_limited += 1
                self._alert(
                    "concurrency_limited",
                    "warning",
                    tenant_id,
                    usage.in_flight,
                    quota.max_concurrent_runs,
                    "ops-rate-limit",
                )
                return Admission(False, CONCURRENCY_LIMITED, 1.0)
            bucket = self._refill(tenant_id, quota, now)
            if bucket.tokens < 1.0:
                usage.rate_limited += 1
                self._alert("rate_limited", "warning", tenant_id, usage.rate_limited, 1, "ops-rate-limit")
                return Admission(
                    False, RATE_LIMITED, math.ceil((1.0 - bucket.tokens) / (quota.requests_per_minute / 60.0))
                )
            bucket.tokens -= 1.0
            usage.in_flight += 1
            usage.admitted += 1
            return Admission(True)

    def finish(
        self,
        tenant_id: str,
        *,
        run_ref: str | None = None,
        cost_units: float = 0.0,
        purpose: str | None = None,
        dialect: str | None = None,
    ) -> None:
        """Release the concurrency slot and attribute the cost (once per run)."""
        quota, now = self.policy.quota_for(tenant_id), self._clock()
        with self._lock:
            usage = self._roll(tenant_id, now)
            usage.in_flight = max(0, usage.in_flight - 1)
            if cost_units > 0 and (run_ref is None or (tenant_id, run_ref) not in self._recorded):
                if run_ref is not None:
                    self._recorded.add((tenant_id, run_ref))
                usage.day_cost_units += cost_units
                if purpose:
                    usage.by_purpose[purpose] += cost_units
                if dialect:
                    usage.by_dialect[dialect] += cost_units
                if usage.day_cost_units >= quota.daily_cost_units * quota.warn_fraction:
                    severity_kind = (
                        "cost_budget_exhausted"
                        if usage.day_cost_units >= quota.daily_cost_units
                        else "cost_budget_warning"
                    )
                    self._alert(
                        severity_kind,
                        "page" if severity_kind == "cost_budget_exhausted" else "warning",
                        tenant_id,
                        usage.day_cost_units,
                        quota.daily_cost_units,
                        "ops-cost-budget",
                    )

    def usage(self, tenant_id: str) -> TenantUsage:
        with self._lock:
            return self._roll(tenant_id, self._clock())

    # ---- internals ----

    def _refill(self, tenant_id: str, quota: TenantQuota, now: datetime) -> _Bucket:
        bucket = self._buckets.get(tenant_id)
        if bucket is None:
            bucket = self._buckets[tenant_id] = _Bucket(tokens=float(quota.burst), updated=now)
        elapsed = max(0.0, (now - bucket.updated).total_seconds())
        bucket.tokens = min(float(quota.burst), bucket.tokens + elapsed * quota.requests_per_minute / 60.0)
        bucket.updated = now
        return bucket

    def _roll(self, tenant_id: str, now: datetime) -> TenantUsage:
        usage = self._usage[tenant_id]
        today = now.astimezone(timezone.utc).date().isoformat()
        if usage.day != today:  # the daily budget resets at 00:00 UTC; concurrency and rate state carry over
            usage.day, usage.day_cost_units = today, 0.0
            usage.by_purpose, usage.by_dialect = defaultdict(float), defaultdict(float)
            self._alerted = {key for key in self._alerted if not (key[0] == tenant_id and key[1].startswith("cost"))}
        return usage

    @staticmethod
    def _seconds_to_midnight(now: datetime) -> float:
        utc = now.astimezone(timezone.utc)
        return float(86_400 - (utc.hour * 3600 + utc.minute * 60 + utc.second))

    def _alert(self, kind: str, severity: str, tenant_id: str, value: float, threshold: float, runbook: str) -> None:
        key = (tenant_id, kind, self._usage[tenant_id].day if kind.startswith("cost") else "")
        if key in self._alerted:
            return  # one alert per condition (per day for budgets) rather than one per request
        self._alerted.add(key)
        self.alerts.append(
            OpsAlert(
                kind=kind,
                severity=severity,
                tenant_id=tenant_id,
                value=float(value),
                threshold=float(threshold),
                runbook_id=runbook,
            )
        )


class SloTracker:
    """Error-budget burn rates and latency per tenant over sliding windows."""

    def __init__(self, policy: QuotaPolicy, *, clock: Clock = lambda: datetime.now(timezone.utc)) -> None:
        self.policy, self._clock = policy, clock
        self._events: dict[str, deque[tuple[datetime, bool, float]]] = defaultdict(deque)
        self._lock = threading.Lock()
        self.alerts: list[OpsAlert] = []

    def record(self, tenant_id: str, *, ok: bool, latency_seconds: float) -> None:
        now = self._clock()
        with self._lock:
            events = self._events[tenant_id]
            events.append((now, ok, latency_seconds))
            horizon = now.timestamp() - self.policy.slo.slow_window_seconds
            while events and events[0][0].timestamp() < horizon:
                events.popleft()

    def burn_rate(self, tenant_id: str, window_seconds: int) -> tuple[float, int]:
        slo, now = self.policy.slo, self._clock()
        with self._lock:
            recent = [e for e in self._events[tenant_id] if e[0].timestamp() >= now.timestamp() - window_seconds]
        if not recent:
            return 0.0, 0
        error_rate = sum(1 for e in recent if not e[1]) / len(recent)
        return error_rate / (1.0 - slo.success_target), len(recent)

    def p95(self, tenant_id: str, window_seconds: int) -> float | None:
        now = self._clock()
        with self._lock:
            values = sorted(
                e[2] for e in self._events[tenant_id] if e[0].timestamp() >= now.timestamp() - window_seconds
            )
        return values[max(0, math.ceil(0.95 * len(values)) - 1)] if values else None

    def evaluate(self, tenant_id: str) -> list[OpsAlert]:
        slo, raised = self.policy.slo, []
        fast, fast_n = self.burn_rate(tenant_id, slo.fast_window_seconds)
        slow, slow_n = self.burn_rate(tenant_id, slo.slow_window_seconds)
        if fast_n >= slo.min_requests and fast >= slo.fast_burn_rate:
            raised.append(
                OpsAlert(
                    kind="slo_fast_burn",
                    severity="page",
                    tenant_id=tenant_id,
                    value=fast,
                    threshold=slo.fast_burn_rate,
                    runbook_id="ops-slo-burn",
                )
            )
        if slow_n >= slo.min_requests and slow >= slo.slow_burn_rate:
            raised.append(
                OpsAlert(
                    kind="slo_slow_burn",
                    severity="warning",
                    tenant_id=tenant_id,
                    value=slow,
                    threshold=slo.slow_burn_rate,
                    runbook_id="ops-slo-burn",
                )
            )
        p95 = self.p95(tenant_id, slo.slow_window_seconds)
        if slow_n >= slo.min_requests and p95 is not None and p95 > slo.p95_latency_seconds:
            raised.append(
                OpsAlert(
                    kind="slo_latency",
                    severity="warning",
                    tenant_id=tenant_id,
                    value=p95,
                    threshold=slo.p95_latency_seconds,
                    runbook_id="ops-slo-latency",
                )
            )
        self.alerts.extend(raised)
        return raised
