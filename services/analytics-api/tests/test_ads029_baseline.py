from datetime import datetime, timezone

import pytest

from app.harness import (
    BaselineLock,
    BaselineLockError,
    GradeCase,
    ThresholdChangeApproval,
    grade_case,
)


def test_baseline_comparison_reports_regressions():
    baseline = BaselineLock(
        baseline_id="baseline-1", suite_version="suite-1", fixture_digest="fixtures-1",
        thresholds={"retrieval": 1.0, "intent": 1.0, "trace": 1.0},
    )
    report = grade_case(GradeCase(case_id="case-1", suite_version="suite-1", trace_valid=False))
    comparison = baseline.compare(report)
    assert comparison.blocked
    assert any("trace" in regression for regression in comparison.regressions)


def test_baseline_changes_require_independent_approval():
    baseline = BaselineLock(
        baseline_id="baseline-1", suite_version="suite-1", fixture_digest="fixtures-1",
        thresholds={"trace": 1.0},
    )
    candidate = baseline.model_copy(update={"thresholds": {"trace": 0.9}})
    with pytest.raises(BaselineLockError, match="requires independent approval"):
        baseline.validate_candidate(candidate)
    approval = ThresholdChangeApproval(
        approval_id="approval-1", baseline_id="baseline-1", reviewer="reviewer-1",
        rationale="Approved after reviewing the pinned local fixture limitation.",
        approved_at=datetime(2026, 9, 23, tzinfo=timezone.utc),
    )
    baseline.validate_candidate(candidate, approval)
