"""Result shape, grain, invariant, and fingerprint validation (ADS-041).

A gateway result is only evidence of what the database returned. This module checks it
against what the certified intent promised, and against an independent control query
(the same metrics and filters with no grouping), so fanout, missing groups, invalid
totals, and truncation fail closed before anything can explain the result. Issue
details describe the check, never row values.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from app.execution.gateway import ExecutionGateway, ExecutionLimits, ExecutionResult
from packages.platform_contracts.analytics_intent import AnalyticalIntent, IntentSort
from packages.platform_contracts.semantic import SemanticContract

Severity = Literal["blocking", "warning"]
_ADDITIVE = {"sum", "count"}
_REL_TOLERANCE = Decimal("1e-9")


@dataclass(frozen=True)
class ResultIssue:
    code: str
    severity: Severity
    detail: str


@dataclass(frozen=True)
class ResultValidationReport:
    status: Literal["valid", "valid_with_warnings", "invalid"]
    issues: tuple[ResultIssue, ...]
    result_fingerprint: str
    plan_fingerprint: str
    row_count: int
    checks: tuple[str, ...]

    @property
    def acceptable(self) -> bool:
        return self.status != "invalid"

    @property
    def blocking_codes(self) -> tuple[str, ...]:
        return tuple(issue.code for issue in self.issues if issue.severity == "blocking")

    @property
    def fingerprint(self) -> str:
        """Digest binding the verdict to the exact result and plan it was computed for."""
        return _digest([self.status, self.result_fingerprint, self.plan_fingerprint, list(self.blocking_codes)])


def result_fingerprint(result: ExecutionResult) -> str:
    """Canonical digest of the returned data; stable across processes and replays."""
    return _digest(
        {
            "dialect": result.dialect,
            "columns": list(result.columns),
            "rows": [[_canonical(value) for value in row] for row in result.rows],
            "truncated": result.truncated,
            "reason": result.truncation_reason,
        }
    )


def plan_fingerprint(plan: Any) -> str:
    return _digest(
        {
            "dialect": getattr(plan, "dialect", None),
            "sql": plan.sql,
            "parameters": {key: _canonical(value) for key, value in sorted(dict(plan.parameters).items())},
        }
    )


def control_intent(intent: AnalyticalIntent) -> AnalyticalIntent:
    """The same question with no grouping: its single row is the ground truth for totals."""
    return intent.model_copy(update={"group_by": [], "sort": [], "limit": 1})


def run_control_totals(
    intent: AnalyticalIntent,
    contract: SemanticContract,
    *,
    compile_plan: Callable[[AnalyticalIntent, SemanticContract], Any],
    gateway: ExecutionGateway,
    limits: ExecutionLimits,
) -> dict[str, Any]:
    """Compile and run the control query through the same governed path; returns metric -> value.

    `compile_plan` must apply the same policy values as the primary compile (row filters
    included), otherwise the totals would describe a different population.
    """
    plan = compile_plan(control_intent(intent), contract)
    result = gateway.execute(plan, limits=limits)
    if result.row_count != 1 or len(result.rows[0]) != len(intent.metrics):
        raise ValueError("control query did not return exactly one row of metrics")
    return {metric.metric_id: value for metric, value in zip(intent.metrics, result.rows[0], strict=True)}


def validate_result(
    result: ExecutionResult,
    plan: Any,
    intent: AnalyticalIntent,
    contract: SemanticContract,
    *,
    control_totals: Mapping[str, Any] | None = None,
    require_control_totals: bool = True,
    expected_fingerprint: str | None = None,
) -> ResultValidationReport:
    issues: list[ResultIssue] = []
    checks: list[str] = []

    def block(code: str, detail: str) -> None:
        issues.append(ResultIssue(code, "blocking", detail))

    def warn(code: str, detail: str) -> None:
        issues.append(ResultIssue(code, "warning", detail))

    actual_fingerprint = result_fingerprint(result)
    if expected_fingerprint is not None:
        checks.append("fingerprint")
        if expected_fingerprint != actual_fingerprint:
            block("fingerprint_mismatch", "result does not match the recorded fingerprint")
    checks.append("provenance")
    if result.dialect != getattr(plan, "dialect", None):
        block("dialect_mismatch", "result was produced by a different dialect than the plan")

    checks.append("truncation")
    if result.truncated:
        block(f"truncated_{result.truncation_reason or 'unknown'}", "result is incomplete; it cannot support an answer")

    group_count = len(intent.group_by)
    expected_columns = tuple(
        [f"dimension_{index}" for index in range(group_count)]
        + [f"metric_{index}" for index in range(len(intent.metrics))]
    )
    checks.append("shape")
    shape_ok = result.columns == expected_columns and all(len(row) == len(expected_columns) for row in result.rows)
    if not shape_ok:
        block("shape_mismatch", "columns or row widths differ from the certified intent")

    checks.append("limit")
    if result.row_count > intent.limit:
        block("limit_exceeded", "result has more rows than the intent limit")
    elif result.row_count == intent.limit and group_count and not result.truncated:
        warn("limit_reached", "result may be a top-N slice; more groups can exist")

    if shape_ok:
        metrics = _metric_specs(intent, contract)
        invalid_metrics = _check_metric_values(result, group_count, metrics, block)
        checks.append("grain")
        _check_grain(result, group_count, block)
        checks.append("sort")
        _check_sort(result, intent, group_count, block)
        checks.append("reconciliation")
        _check_reconciliation(
            result,
            intent,
            group_count,
            metrics,
            control_totals,
            require_control_totals,
            block,
            warn,
            skip=invalid_metrics,
        )

    blocking = any(issue.severity == "blocking" for issue in issues)
    status = "invalid" if blocking else "valid_with_warnings" if issues else "valid"
    return ResultValidationReport(
        status=status,
        issues=tuple(issues),
        result_fingerprint=actual_fingerprint,
        plan_fingerprint=plan_fingerprint(plan),
        row_count=result.row_count,
        checks=tuple(checks),
    )


def _metric_specs(intent: AnalyticalIntent, contract: SemanticContract) -> list[tuple[str, str]]:
    aggregations = {metric.id: metric.aggregation for metric in contract.metrics}
    return [(selected.metric_id, aggregations[selected.metric_id]) for selected in intent.metrics]


def _check_metric_values(result, group_count, metrics, block) -> set[str]:
    """Report malformed metric cells; returns metric IDs that cannot be reconciled."""
    invalid: set[str] = set()
    for offset, (metric_id, aggregation) in enumerate(metrics):
        column = group_count + offset
        for row in result.rows:
            value = row[column]
            if value is None:
                if aggregation in {"count", "count_distinct"}:
                    block("invalid_metric_value", f"{aggregation} metric {metric_id} returned null")
                    invalid.add(metric_id)
                    break
                continue
            if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
                block("invalid_metric_value", f"metric {metric_id} returned a non-numeric value")
                invalid.add(metric_id)
                break
            if isinstance(value, float) and not math.isfinite(value):
                block("invalid_metric_value", f"metric {metric_id} returned a non-finite value")
                invalid.add(metric_id)
                break
            if aggregation in {"count", "count_distinct"} and (value < 0 or value != int(value)):
                block("invalid_metric_value", f"{aggregation} metric {metric_id} is not a non-negative integer")
                invalid.add(metric_id)
                break
    return invalid


def _check_grain(result, group_count, block) -> None:
    if group_count == 0:
        if result.row_count != 1 and not result.truncated:
            block("grain_cardinality", "an ungrouped aggregate must return exactly one row")
        return
    keys = [tuple(_canonical(value) for value in row[:group_count]) for row in result.rows]
    if len(set(keys)) != len(keys):
        block("duplicate_group_keys", "the same group appears more than once")


def _check_sort(result, intent, group_count, block) -> None:
    if not intent.sort or result.row_count < 2:
        return
    positions = {"dimension": {g.dimension_id: i for i, g in enumerate(intent.group_by)}}
    positions["metric"] = {m.metric_id: group_count + i for i, m in enumerate(intent.metrics)}

    def violates(sort: IntentSort, earlier: Any, later: Any) -> int:
        """-1 ordered, 0 tie, 1 violated; nulls are not compared."""
        if earlier is None or later is None:
            return 0
        try:
            if earlier == later:
                return 0
            ordered = earlier < later if sort.direction == "asc" else earlier > later
        except TypeError:
            return 1
        return -1 if ordered else 1

    for previous, current in zip(result.rows, result.rows[1:], strict=False):
        for sort in intent.sort:
            index = positions[sort.target_kind][sort.target_id]
            verdict = violates(sort, previous[index], current[index])
            if verdict == 1:
                block("sort_violated", "rows are not in the order the intent requested")
                return
            if verdict == -1:
                break


def _check_reconciliation(
    result, intent, group_count, metrics, totals, required, block, warn, *, skip=frozenset()
) -> None:
    if not group_count:
        return  # a single aggregate row is its own total
    if result.truncated or result.row_count >= intent.limit:
        warn("reconciliation_skipped", "result is partial, so group values cannot be summed to a total")
        return
    for offset, (metric_id, aggregation) in enumerate(metrics):
        if aggregation == "ratio" or metric_id in skip:
            continue
        if totals is None or metric_id not in totals or totals[metric_id] is None:
            if required:
                block("reconciliation_missing", f"no control total for metric {metric_id}")
            else:
                warn("reconciliation_missing", f"no control total for metric {metric_id}")
            continue
        try:
            total = _decimal(totals[metric_id])
            if not total.is_finite():
                raise ArithmeticError
        except (ArithmeticError, ValueError):
            block("invalid_total", f"control total for metric {metric_id} is not a finite number")
            continue
        values = [_decimal(row[group_count + offset]) for row in result.rows if row[group_count + offset] is not None]
        if aggregation in _ADDITIVE:
            observed = sum(values, Decimal(0))
            if _differs(observed, total):
                if observed > total:
                    block("fanout_suspected", f"groups of {metric_id} add up to more than the control total")
                else:
                    block("missing_groups_suspected", f"groups of {metric_id} add up to less than the control total")
        elif not values:
            block("missing_groups_suspected", f"metric {metric_id} has a control total but no group values")
        elif aggregation == "max" and _differs(max(values), total):
            block("invalid_total", f"largest group maximum of {metric_id} differs from the control maximum")
        elif aggregation == "min" and _differs(min(values), total):
            block("invalid_total", f"smallest group minimum of {metric_id} differs from the control minimum")
        elif aggregation == "average" and not (min(values) - _slack(total) <= total <= max(values) + _slack(total)):
            block("invalid_total", f"control average of {metric_id} lies outside the range of group averages")
        elif aggregation == "count_distinct" and not (max(values) <= total <= sum(values, Decimal(0))):
            block("invalid_total", f"control distinct count of {metric_id} is outside the bounds implied by its groups")


def _decimal(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _slack(reference: Decimal) -> Decimal:
    return abs(reference) * _REL_TOLERANCE


def _differs(left: Decimal, right: Decimal) -> bool:
    return abs(left - right) > max(abs(left), abs(right)) * _REL_TOLERANCE


def _canonical(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (bytes, bytearray)):
        return value.hex()
    return value if value is None or isinstance(value, (str, int, bool)) else str(value)


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
