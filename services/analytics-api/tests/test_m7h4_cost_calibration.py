"""M7-H4: cost calibration is fitted from measured samples, proposed until a person approves it, and never applied before that."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from reference_stack import calibration_eval as ev
from reference_stack.stack import build_stack

from app.execution.calibration import CalibratedCostEstimator, CalibrationError, calibrated_units, fit_calibration
from packages.platform_contracts.cost_calibration import CalibrationApproval, CostCalibration, CostSample


def _samples(scale=2.0, offset=1.0, n=12, dialect="duckdb"):
    return [
        CostSample(dialect=dialect, estimated_units=float(10 + 5 * i), observed=scale * (10 + 5 * i) + offset)
        for i in range(n)
    ]


def _approved(calibration: CostCalibration) -> CostCalibration:
    approval = CalibrationApproval(status="approved", approved_by="a named person", approved_at="2026-10-13")
    return calibration.model_copy(update={"approval": approval})


def test_the_mechanism_checks_all_pass():
    checks = ev.mechanism_checks()
    assert len(checks) >= 8 and all(c["ok"] for c in checks), [c for c in checks if not c["ok"]]


def test_a_fit_is_proposed_and_records_what_it_was_measured_on():
    fitted = fit_calibration(
        _samples(), version="v1", unit="ms", calibrated_against="the staging warehouse", valid_for_production=True
    )
    assert fitted.approval.status == "proposed" and fitted.approval.approved_by is None
    assert fitted.fits["duckdb"].samples == 12 and fitted.calibrated_against == "the staging warehouse"


def test_an_approval_needs_a_person_and_a_date():
    with pytest.raises(ValidationError):
        CalibrationApproval(status="approved")
    with pytest.raises(ValidationError):
        CalibrationApproval(status="approved", approved_by="someone")
    with pytest.raises(ValidationError):
        CostSample(dialect="d", estimated_units=0, observed=1)


def test_a_calibration_is_applied_only_when_approved_and_valid_for_production():
    proposed = fit_calibration(_samples(), version="v1", unit="ms", calibrated_against="x", valid_for_production=True)
    assert calibrated_units(proposed, "duckdb", 50.0) == (50.0, False)
    assert calibrated_units(_approved(proposed), "duckdb", 50.0) == (101.0, True)
    local = _approved(
        fit_calibration(_samples(), version="v1", unit="ms", calibrated_against="x", valid_for_production=False)
    )
    assert calibrated_units(local, "duckdb", 50.0) == (50.0, False)
    assert calibrated_units(None, "duckdb", 50.0) == (50.0, False)
    assert calibrated_units(_approved(proposed), "postgres", 50.0) == (50.0, False)  # no fit for that dialect


def test_unsound_samples_are_refused():
    for rows, code in (
        (_samples(n=4), "too_few_samples"),
        (
            [CostSample(dialect="d", estimated_units=3.0, observed=float(i + 1)) for i in range(12)],
            "estimates_do_not_vary",
        ),
        (
            [CostSample(dialect="d", estimated_units=float(i + 1), observed=float(50 - i)) for i in range(12)],
            "estimates_do_not_predict_cost",
        ),
        ([], "no_samples"),
    ):
        with pytest.raises(CalibrationError) as caught:
            fit_calibration(rows, version="v", unit="u", calibrated_against="x", valid_for_production=True)
        assert caught.value.code.startswith(code)


def test_the_estimator_reports_whether_its_last_number_was_calibrated():
    class Raw:
        def estimate(self, plan):
            return 50.0

    class Plan:
        dialect = "duckdb"

    proposed = fit_calibration(_samples(), version="v1", unit="ms", calibrated_against="x", valid_for_production=True)
    estimator = CalibratedCostEstimator(Raw(), proposed)
    assert estimator.estimate(Plan()) == 50.0 and estimator.last_calibrated is False
    estimator = CalibratedCostEstimator(Raw(), _approved(proposed))
    assert estimator.estimate(Plan()) == 101.0 and estimator.last_calibrated is True


def test_the_reference_stack_uses_an_approved_calibration_and_ignores_a_proposed_one(tmp_path):
    def estimated(calibration, name):
        stack = build_stack("duckdb", tmp_path / name, cost_calibration=calibration)
        who = stack.verifier().verify(stack.token("requester"))
        run = stack.service().analyze(
            who, purpose="analytics", idempotency_key=f"cal-key-{name}-1", request_text="Show monthly revenue"
        )
        state = stack.control.load_latest_checkpoint(run_id=run.run_id, tenant_id=who.tenant_id, purpose="analytics")
        return state.cost_decision["estimated_cost_units"]

    samples = [
        CostSample(dialect="duckdb", estimated_units=float(10 + 5 * i), observed=2.0 * (10 + 5 * i)) for i in range(12)
    ]
    proposed = fit_calibration(samples, version="v1", unit="ms", calibrated_against="x", valid_for_production=True)
    raw = estimated(None, "raw")
    assert estimated(proposed, "proposed") == raw
    assert estimated(_approved(proposed), "approved") == pytest.approx(raw * 2.0)


def test_the_local_measurement_is_informational_and_the_report_says_it_is_not_a_calibration():
    report = ev.run_calibration()
    text = ev.render_markdown(report)
    assert report["ok"] and "not a warehouse calibration" in text
    assert set(report["local_measurement"]) == {"duckdb", "postgres"}


def test_a_fit_with_a_negative_intercept_is_refused():
    # observed = 3 * estimate - 50, all positive for estimates of 20 and more: the fitted intercept is -50
    rows = [
        CostSample(dialect="d", estimated_units=float(20 + 5 * i), observed=3.0 * (20 + 5 * i) - 50.0)
        for i in range(12)
    ]
    with pytest.raises(CalibrationError) as caught:
        fit_calibration(rows, version="v", unit="u", calibrated_against="x", valid_for_production=True)
    assert caught.value.code == "negative_intercept:d"
