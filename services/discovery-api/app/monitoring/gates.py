"""Deterministic offline quality gates for immersive discovery."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,31}$")
_COHORT = re.compile(r"^[a-z][a-z0-9_-]{0,31}:[a-z0-9][a-z0-9_-]{0,31}$")
_PRIVATE_LABELS = {"query", "profile", "user", "social", "history", "prompt"}
_MAX_SLICES = 64


class GateStatus(str, Enum):
    """Stable status vocabulary for offline reports."""

    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"


@dataclass(frozen=True)
class MetricObservation:
    """One aggregate metric for a bounded cohort slice."""

    metric_id: str
    value: float
    sample_count: int
    metric_version: str = "v1"
    cohort: str = "all"
    missing_count: int = 0

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("metric_id must be non-empty")
        if not math.isfinite(self.value):
            raise ValueError("metric value must be finite")
        if isinstance(self.sample_count, bool) or self.sample_count < 1:
            raise ValueError("sample_count must be at least 1")
        if isinstance(self.missing_count, bool) or not 0 <= self.missing_count <= self.sample_count:
            raise ValueError("missing_count must be between zero and sample_count")
        if not _VERSION.fullmatch(self.metric_version):
            raise ValueError("metric_version is invalid")
        _validate_cohort(self.cohort)


@dataclass(frozen=True)
class GateThreshold:
    """Versioned limits for one metric and one monitoring gate."""

    metric_id: str
    metric_version: str = "v1"
    minimum_samples: int = 20
    maximum_drift: float = 0.1
    maximum_calibration_error: float = 0.1
    maximum_regression: float = 0.05
    maximum_missing_rate: float = 0.0

    def __post_init__(self) -> None:
        if not self.metric_id.strip():
            raise ValueError("threshold metric_id must be non-empty")
        if not _VERSION.fullmatch(self.metric_version):
            raise ValueError("threshold metric_version is invalid")
        if isinstance(self.minimum_samples, bool) or self.minimum_samples < 1:
            raise ValueError("minimum_samples must be at least 1")
        for name in (
            "maximum_drift",
            "maximum_calibration_error",
            "maximum_regression",
            "maximum_missing_rate",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value < 0 or value > 1:
                raise ValueError(f"{name} must be finite and in [0, 1]")


@dataclass(frozen=True)
class GateResult:
    """Decision for one metric/cohort pair with safe evidence only."""

    metric_id: str
    cohort: str
    status: GateStatus
    reasons: tuple[str, ...]
    sample_count: int
    missing_rate: float
    drift: float | None
    regression: float | None
    metric_version: str


@dataclass(frozen=True)
class MonitoringReport:
    """Stable report; it never promotes models or mutates serving state."""

    report_version: str
    status: GateStatus
    results: tuple[GateResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "report_version": self.report_version,
            "status": self.status.value,
            "results": [
                {
                    "metric_id": result.metric_id,
                    "cohort": result.cohort,
                    "status": result.status.value,
                    "reasons": list(result.reasons),
                    "sample_count": result.sample_count,
                    "missing_rate": result.missing_rate,
                    "drift": result.drift,
                    "regression": result.regression,
                    "metric_version": result.metric_version,
                }
                for result in self.results
            ],
        }

    def serialize(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))


def evaluate_monitoring_gates(
    current: Iterable[MetricObservation],
    *,
    baseline: Iterable[MetricObservation] = (),
    thresholds: Iterable[GateThreshold],
    report_version: str = "imd-monitoring-v1",
) -> MonitoringReport:
    """Evaluate drift, calibration, regression, slice, and missing-data gates.

    Inputs are aggregate offline evidence. Results are sorted by metric and
    cohort, making reports independent of source iteration order.
    """
    if not _VERSION.fullmatch(report_version.replace("imd-monitoring-", "v1")):
        raise ValueError("report_version is invalid")
    current_rows = _unique_observations(current, "current")
    baseline_rows = _unique_observations(baseline, "baseline")
    threshold_map = _unique_thresholds(thresholds)
    if len({row.cohort for row in current_rows.values()}) > _MAX_SLICES:
        raise ValueError("slice count exceeds bounded limit")
    results: list[GateResult] = []
    for row in current_rows.values():
        threshold = threshold_map.get(row.metric_id)
        if threshold is None:
            raise ValueError(f"missing threshold for metric {row.metric_id}")
        if row.metric_version != threshold.metric_version:
            raise ValueError("metric-version mismatch")
        if row.sample_count < threshold.minimum_samples:
            raise ValueError("insufficient samples")
        base = baseline_rows.get((row.metric_id, row.cohort))
        drift = abs(row.value - base.value) if base else None
        regression = base.value - row.value if base else None
        missing_rate = row.missing_count / row.sample_count
        reasons: list[str] = []
        if drift is not None and drift > threshold.maximum_drift:
            reasons.append("drift_exceeded")
        if row.metric_id == "calibration_error" and row.value > threshold.maximum_calibration_error:
            reasons.append("calibration_exceeded")
        if regression is not None and regression > threshold.maximum_regression:
            reasons.append("regression_exceeded")
        if missing_rate > threshold.maximum_missing_rate:
            reasons.append("missing_data_exceeded")
        elif missing_rate:
            reasons.append("missing_data")
        status = GateStatus.FAIL if any(reason.endswith("exceeded") for reason in reasons) else (
            GateStatus.DEGRADED if reasons else GateStatus.PASS
        )
        results.append(
            GateResult(
                metric_id=row.metric_id,
                cohort=row.cohort,
                status=status,
                reasons=tuple(sorted(reasons)),
                sample_count=row.sample_count,
                missing_rate=missing_rate,
                drift=drift,
                regression=regression,
                metric_version=row.metric_version,
            )
        )
    results.sort(key=lambda result: (result.metric_id, result.cohort))
    overall = GateStatus.FAIL if any(result.status is GateStatus.FAIL for result in results) else (
        GateStatus.DEGRADED if any(result.status is GateStatus.DEGRADED for result in results) else GateStatus.PASS
    )
    return MonitoringReport(report_version, overall, tuple(results))


def _unique_observations(rows: Iterable[MetricObservation], label: str) -> dict[tuple[str, str], MetricObservation]:
    result: dict[tuple[str, str], MetricObservation] = {}
    for row in rows:
        if not isinstance(row, MetricObservation):
            raise TypeError(f"{label} observations must be MetricObservation values")
        key = (row.metric_id, row.cohort)
        if key in result:
            raise ValueError(f"ambiguous {label} cohort")
        result[key] = row
    return result


def _unique_thresholds(rows: Iterable[GateThreshold]) -> dict[str, GateThreshold]:
    result: dict[str, GateThreshold] = {}
    for row in rows:
        if not isinstance(row, GateThreshold):
            raise TypeError("thresholds must be GateThreshold values")
        if row.metric_id in result:
            raise ValueError("ambiguous metric threshold")
        result[row.metric_id] = row
    if not result:
        raise ValueError("at least one threshold is required")
    return result


def _validate_cohort(cohort: str) -> None:
    if cohort == "all":
        return
    if not isinstance(cohort, str) or not _COHORT.fullmatch(cohort):
        raise ValueError("cohort must be a bounded dimension:value label")
    dimension = cohort.split(":", 1)[0]
    if dimension in _PRIVATE_LABELS:
        raise ValueError("private cohort dimensions are not allowed")


__all__ = [
    "GateResult",
    "GateStatus",
    "GateThreshold",
    "MetricObservation",
    "MonitoringReport",
    "evaluate_monitoring_gates",
]
