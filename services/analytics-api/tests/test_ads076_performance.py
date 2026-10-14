"""ADS-076: latency, concurrency, tokens, cost, and fairness are measured against proposed gates, and each gate can fail."""

from __future__ import annotations

import copy
import json

import pytest
from reference_stack import performance_eval as ev

from app.quotas import QuotaManager
from app.quotas import manager as quota_manager

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())
SMALL = {"warm": 12, "workers": 3, "per_worker": 4}


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ev.run_performance(root=tmp_path_factory.mktemp("performance"), **SMALL)


def test_the_thresholds_are_proposed_and_the_prices_are_labelled_placeholders():
    assert THRESHOLDS["approval"]["status"] == "proposed" and THRESHOLDS["approval"]["approved_by"] is None
    assert "PLACEHOLDERS" in THRESHOLDS["assumed_prices"]["note"]
    assert THRESHOLDS["gates"]["p95_warm_latency_seconds"]["value"] == 8.0
    assert THRESHOLDS["gates"]["p95_compile_policy_overhead_ms"]["value"] == 250.0


def test_latency_concurrency_tokens_and_fairness_meet_their_gates(report):
    unmet = {n for n, g in report["gates"].items() if not g["meets"]}
    assert unmet <= {"answers_per_tenant_day"}, unmet  # the only gate allowed to fail is the one the report explains
    assert report["gates"]["concurrent_errors_or_wrong_rows"]["value"] == 0
    assert (
        report["gates"]["quiet_tenant_denials"]["value"] == 0
        and report["gates"]["noisy_tenant_over_quota"]["value"] == 0
    )
    assert report["samples"]["concurrent_requests"] == 2 * 3 * 4


def test_the_proposed_daily_budget_is_reported_against_the_uncalibrated_cost_units(report):
    gate = report["gates"]["answers_per_tenant_day"]
    low, high = report["samples"]["cost_units_range"]
    assert high > low * 4  # the units differ widely by query and dialect: they are not calibrated
    assert gate["value"] == pytest.approx(
        report["samples"]["daily_cost_units"] / report["gates"]["warehouse_cost_units_per_answer"]["value"]
    )


def test_the_report_says_what_it_does_not_show(report):
    text = ev.render_markdown(report)
    assert "say nothing about a real model or warehouse" in text and "placeholders, not quotes" in text
    assert "real_model_latency" in text and "NOT APPROVED" in text


def test_a_slow_system_fails_the_latency_gate(tmp_path):
    strict = copy.deepcopy(THRESHOLDS)
    strict["gates"]["p95_warm_latency_seconds"]["value"] = 1e-9
    report = ev.run_performance(thresholds=strict, root=tmp_path, **SMALL)
    assert not report["gates"]["p95_warm_latency_seconds"]["meets"] and not report["ok"]


def test_wrong_rows_under_concurrency_fail_the_correctness_gate(monkeypatch, tmp_path):
    monkeypatch.setitem(ev.QUESTIONS, "Revenue by status", [["nonsense", "0"]])
    report = ev.run_performance(root=tmp_path, **SMALL)
    assert report["gates"]["concurrent_errors_or_wrong_rows"]["value"] > 0 and not report["ok"]


def test_a_quota_manager_that_admits_everything_fails_the_noisy_neighbour_gate(monkeypatch):
    monkeypatch.setattr(QuotaManager, "admit", lambda self, tenant_id: quota_manager.Admission(True))
    shared = ev.fairness()
    assert shared["noisy"]["admitted"] == shared["noisy"]["offered"] > shared["noisy"]["allowed_at_most"]


def test_the_real_quota_manager_holds_a_noisy_tenant_to_its_quota_and_spares_a_quiet_one():
    shared = ev.fairness()
    assert shared["noisy"]["admitted"] <= shared["noisy"]["allowed_at_most"]
    assert shared["quiet"]["admitted"] == shared["quiet"]["offered"] and not shared["quiet"]["denied"]
    assert set(shared["noisy"]["denied"]) <= {"rate_limited", "concurrency_limited"}
