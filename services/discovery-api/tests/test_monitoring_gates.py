import json

import pytest

from app.monitoring.gates import (
    GateStatus,
    GateThreshold,
    MetricObservation,
    evaluate_monitoring_gates,
)


def _threshold(metric_id: str = "recall_at_k") -> GateThreshold:
    return GateThreshold(
        metric_id=metric_id,
        minimum_samples=10,
        maximum_drift=0.1,
        maximum_regression=0.05,
        maximum_missing_rate=0.2,
    )


def test_report_is_deterministic_and_covers_slices() -> None:
    current = [
        MetricObservation("recall_at_k", 0.82, 20, cohort="locale:en-us"),
        MetricObservation("recall_at_k", 0.75, 20),
    ]
    baseline = [
        MetricObservation("recall_at_k", 0.8, 20, cohort="locale:en-us"),
        MetricObservation("recall_at_k", 0.75, 20),
    ]
    report = evaluate_monitoring_gates(
        reversed(current),
        baseline=reversed(baseline),
        thresholds=[_threshold()],
    )
    assert report.status is GateStatus.PASS
    assert [result.cohort for result in report.results] == ["all", "locale:en-us"]
    assert json.loads(report.serialize()) == json.loads(report.serialize())


def test_drift_calibration_regression_and_missing_data_are_explicit() -> None:
    report = evaluate_monitoring_gates(
        [MetricObservation("calibration_error", 0.4, 10, missing_count=1)],
        baseline=[MetricObservation("calibration_error", 0.1, 10)],
        thresholds=[
            GateThreshold(
                "calibration_error",
                minimum_samples=10,
                maximum_drift=0.05,
                maximum_calibration_error=0.2,
                maximum_regression=0.05,
                maximum_missing_rate=0.2,
            )
        ],
    )
    result = report.results[0]
    assert report.status is GateStatus.FAIL
    assert result.status is GateStatus.FAIL
    assert result.reasons == ("calibration_exceeded", "drift_exceeded", "missing_data")
    assert result.missing_rate == pytest.approx(0.1)


def test_validation_fails_closed_for_ambiguous_or_private_inputs() -> None:
    with pytest.raises(ValueError, match="ambiguous current cohort"):
        evaluate_monitoring_gates(
            [MetricObservation("recall_at_k", 0.8, 10), MetricObservation("recall_at_k", 0.9, 10)],
            thresholds=[_threshold()],
        )
    with pytest.raises(ValueError, match="private cohort"):
        MetricObservation("recall_at_k", 0.8, 10, cohort="profile:abc")
    with pytest.raises(ValueError, match="insufficient samples"):
        evaluate_monitoring_gates(
            [MetricObservation("recall_at_k", 0.8, 9)], thresholds=[_threshold()]
        )
    with pytest.raises(ValueError, match="metric-version mismatch"):
        evaluate_monitoring_gates(
            [MetricObservation("recall_at_k", 0.8, 10, metric_version="v2")],
            thresholds=[_threshold()],
        )


def test_missing_data_below_threshold_is_degraded() -> None:
    report = evaluate_monitoring_gates(
        [MetricObservation("recall_at_k", 0.8, 10, missing_count=1)],
        thresholds=[_threshold()],
    )
    assert report.status is GateStatus.DEGRADED
    assert report.results[0].reasons == ("missing_data",)
