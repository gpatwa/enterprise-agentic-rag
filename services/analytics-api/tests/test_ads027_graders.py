import pytest

from app.harness import GradeCase, grade_case


def full_case(**changes) -> GradeCase:
    values = {
        "case_id": "ads027-case",
        "suite_version": "ads-m2-v1",
        "expected_retrieval_ids": ("metric:revenue", "dataset:orders"),
        "actual_retrieval_ids": ("metric:revenue", "dataset:orders"),
        "expected_metric_ids": ("revenue",),
        "actual_metric_ids": ("revenue",),
        "expected_dataset_id": "orders",
        "actual_dataset_id": "orders",
        "expected_ast_fingerprint": "ast-1",
        "actual_ast_fingerprint": "ast-1",
        "expected_result_fingerprint": "result-1",
        "actual_result_fingerprint": "result-1",
        "expected_policy": "allow",
        "actual_policy": "allow",
        "trace_valid": True,
        "required_evidence_ids": ("evidence-1",),
        "actual_evidence_ids": ("evidence-1",),
    }
    values.update(changes)
    return GradeCase(**values)


def test_layered_grader_passes_complete_case():
    report = grade_case(full_case())
    assert report.passed
    assert all(finding.passed for finding in report.findings)


@pytest.mark.parametrize(
    ("field", "value", "stage"),
    [
        ("actual_retrieval_ids", ("dataset:orders",), "retrieval"),
        ("actual_metric_ids", ("cost",), "intent"),
        ("actual_ast_fingerprint", "ast-2", "ast"),
        ("actual_result_fingerprint", "result-2", "result"),
        ("actual_policy", "deny", "policy"),
        ("trace_valid", False, "trace"),
        ("actual_evidence_ids", (), "evidence"),
    ],
)
def test_deliberate_defect_fails_only_the_responsible_grader(field, value, stage):
    report = grade_case(full_case(**{field: value}))
    failed = {finding.stage for finding in report.findings if not finding.passed}
    assert failed == {stage}
