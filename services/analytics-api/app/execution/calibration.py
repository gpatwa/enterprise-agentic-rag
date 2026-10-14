"""Fit, check, and apply cost-unit calibrations (M7-H4). Pure code; it never reads a warehouse itself.

`fit_calibration` turns measured samples into a PROPOSED calibration (least squares of observed on estimated, per dialect). It refuses too
few samples, a single repeated estimate, or non-positive values. `CalibratedCostEstimator` applies a calibration only when a person has
approved it AND it is marked valid for production; otherwise it returns the raw estimate and says so, so an uncalibrated number is never
presented as a calibrated one.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from typing import Any

from packages.platform_contracts.cost_calibration import CostCalibration, CostSample, DialectFit

MIN_SAMPLES = 10


class CalibrationError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def fit_calibration(
    samples: Iterable[CostSample], *, version: str, unit: str, calibrated_against: str, valid_for_production: bool
) -> CostCalibration:
    by_dialect: dict[str, list[CostSample]] = defaultdict(list)
    for sample in samples:
        by_dialect[sample.dialect].append(sample)
    if not by_dialect:
        raise CalibrationError("no_samples")
    fits: dict[str, DialectFit] = {}
    for dialect, rows in by_dialect.items():
        if len(rows) < MIN_SAMPLES:
            raise CalibrationError(f"too_few_samples:{dialect}")
        xs, ys = [r.estimated_units for r in rows], [r.observed for r in rows]
        mean_x, mean_y = sum(xs) / len(xs), sum(ys) / len(ys)
        var_x = sum((x - mean_x) ** 2 for x in xs)
        if var_x == 0:
            raise CalibrationError(f"estimates_do_not_vary:{dialect}")
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / var_x
        if slope <= 0:
            raise CalibrationError(f"estimates_do_not_predict_cost:{dialect}")
        offset = mean_y - slope * mean_x
        total = sum((y - mean_y) ** 2 for y in ys)
        residual = sum((y - (slope * x + offset)) ** 2 for x, y in zip(xs, ys, strict=True))
        r_squared = 1.0 if total == 0 else max(0.0, 1.0 - residual / total)
        fits[dialect] = DialectFit(scale=slope, offset=offset, samples=len(rows), r_squared=r_squared)
    return CostCalibration(
        calibration_version=version,
        unit=unit,
        calibrated_against=calibrated_against,
        valid_for_production=valid_for_production,
        fits=fits,
    )


def applicable(calibration: CostCalibration | None, dialect: str) -> bool:
    return (
        calibration is not None
        and calibration.approval.status == "approved"
        and calibration.valid_for_production
        and dialect in calibration.fits
    )


def calibrated_units(calibration: CostCalibration | None, dialect: str, estimated_units: float) -> tuple[float, bool]:
    """(units, calibrated). An unapproved, non-production, or missing calibration returns the raw estimate and False."""
    if not applicable(calibration, dialect):
        return estimated_units, False
    fit = calibration.fits[dialect]  # type: ignore[union-attr]
    return max(0.0, fit.scale * estimated_units + fit.offset), True


class CalibratedCostEstimator:
    """Wraps a `CostEstimator`. `last_calibrated` tells the caller whether the last number was calibrated."""

    def __init__(self, inner: Any, calibration: CostCalibration | None) -> None:
        self._inner, self._calibration = inner, calibration
        self.last_calibrated = False

    def estimate(self, compiled_plan: Any) -> float:
        raw = float(self._inner.estimate(compiled_plan))
        units, self.last_calibrated = calibrated_units(self._calibration, getattr(compiled_plan, "dialect", ""), raw)
        return units
