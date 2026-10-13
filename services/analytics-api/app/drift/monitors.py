"""Pure, deterministic drift statistics and rule evaluation (ADS-058).

Same windows and policy give the same report. A rule with too few samples in either window is skipped and
reported as such rather than guessed at, so a quiet period cannot raise false alarms.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Sequence

from packages.platform_contracts.drift import (
    DriftAlert,
    DriftPolicy,
    DriftReport,
    DriftRule,
    RunObservation,
    SkippedRule,
)

Statistics = Callable[[Sequence[RunObservation]], "float | None"]


def _rate(window: Sequence[RunObservation], predicate) -> float | None:
    return sum(1 for item in window if predicate(item)) / len(window) if window else None


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _p95(values: list[float]) -> float | None:
    """Nearest-rank 95th percentile, so the value is always an observed one."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def outcome_distribution(window: Sequence[RunObservation]) -> dict[str, float]:
    counts = Counter(item.outcome for item in window)
    return {kind: count / len(window) for kind, count in counts.items()} if window else {}


def total_variation_distance(left: dict[str, float], right: dict[str, float]) -> float:
    return 0.5 * sum(abs(left.get(key, 0.0) - right.get(key, 0.0)) for key in set(left) | set(right))


STATISTICS: dict[str, Statistics] = {
    "stale_context_rate": lambda w: _rate(w, lambda o: "stale_context" in o.error_codes),
    "max_context_age_hours": lambda w: max(
        (o.context_age_hours for o in w if o.context_age_hours is not None), default=None
    ),
    "empty_retrieval_rate": lambda w: _rate(
        [o for o in w if o.context_items is not None], lambda o: o.context_items == 0
    ),
    "mean_context_items": lambda w: _mean([o.context_items for o in w if o.context_items is not None]),
    "malformed_intent_rate": lambda w: _rate(w, lambda o: "malformed_model_output" in o.error_codes),
    "clarification_rate": lambda w: _rate(w, lambda o: o.outcome == "clarification_required"),
    "success_rate": lambda w: _rate(w, lambda o: o.outcome == "succeeded"),
    "p95_latency_ms": lambda w: _p95([o.latency_ms for o in w if o.latency_ms is not None]),
    "mean_cost_units": lambda w: _mean([o.cost_units for o in w if o.cost_units is not None]),
}


def _compare(rule: DriftRule, baseline: float | None, current: float) -> tuple[bool, str | None]:
    """Return (drifted, skip_reason)."""
    if rule.comparison == "value":
        return current >= rule.threshold, None
    assert baseline is not None
    if rule.comparison == "abs_increase":
        return current - baseline >= rule.threshold - 1e-12, None
    if rule.comparison == "abs_decrease":
        return baseline - current >= rule.threshold - 1e-12, None
    if baseline <= 0:
        return False, "baseline_zero"
    if rule.comparison == "rel_decrease":
        return (baseline - current) / baseline >= rule.threshold - 1e-12, None
    return current / baseline >= rule.threshold - 1e-12, None  # ratio


def evaluate_drift(
    baseline: Sequence[RunObservation], current: Sequence[RunObservation], policy: DriftPolicy
) -> DriftReport:
    alerts: list[DriftAlert] = []
    skipped: list[SkippedRule] = []
    for rule in policy.rules:
        base_n, cur_n = len(baseline), len(current)
        if rule.statistic == "outcome_distribution_tvd":
            if min(base_n, cur_n) < rule.min_samples:
                skipped.append(
                    SkippedRule(
                        rule_id=rule.rule_id, reason="insufficient_data", baseline_samples=base_n, current_samples=cur_n
                    )
                )
                continue
            base_value = None
            cur_value = total_variation_distance(outcome_distribution(baseline), outcome_distribution(current))
            drifted = cur_value >= rule.threshold - 1e-12
            skip = None
        else:
            stat = STATISTICS[rule.statistic]
            base_value, cur_value_opt = stat(baseline), stat(current)
            if cur_value_opt is None or (rule.comparison != "value" and base_value is None):
                skipped.append(
                    SkippedRule(rule_id=rule.rule_id, reason="no_data", baseline_samples=base_n, current_samples=cur_n)
                )
                continue
            if cur_n < rule.min_samples or (rule.comparison != "value" and base_n < rule.min_samples):
                skipped.append(
                    SkippedRule(
                        rule_id=rule.rule_id, reason="insufficient_data", baseline_samples=base_n, current_samples=cur_n
                    )
                )
                continue
            cur_value = cur_value_opt
            drifted, skip = _compare(rule, base_value, cur_value)
        if skip:
            skipped.append(
                SkippedRule(rule_id=rule.rule_id, reason=skip, baseline_samples=base_n, current_samples=cur_n)
            )
            continue
        if drifted:
            alerts.append(
                DriftAlert(
                    rule_id=rule.rule_id,
                    monitor=rule.monitor,
                    statistic=rule.statistic,
                    severity=rule.severity,
                    runbook_id=rule.runbook_id,
                    baseline_value=base_value,
                    current_value=cur_value,
                    threshold=rule.threshold,
                    comparison=rule.comparison,
                    baseline_samples=base_n,
                    current_samples=cur_n,
                )
            )
    return DriftReport(
        policy_version=policy.policy_version,
        policy_status=policy.approval.status,
        baseline_samples=len(baseline),
        current_samples=len(current),
        alerts=tuple(alerts),
        skipped=tuple(skipped),
    )
