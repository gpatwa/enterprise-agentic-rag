"""Deterministic layered graders for agent harness scenarios."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

GradeStage = Literal["retrieval", "intent", "ast", "result", "policy", "trace", "evidence"]


class GradeCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1, max_length=255)
    suite_version: str = Field(min_length=1, max_length=255)
    expected_retrieval_ids: tuple[str, ...] = ()
    actual_retrieval_ids: tuple[str, ...] = ()
    expected_metric_ids: tuple[str, ...] = ()
    actual_metric_ids: tuple[str, ...] = ()
    expected_dataset_id: str | None = None
    actual_dataset_id: str | None = None
    expected_ast_fingerprint: str | None = None
    actual_ast_fingerprint: str | None = None
    expected_result_fingerprint: str | None = None
    actual_result_fingerprint: str | None = None
    expected_policy: Literal["allow", "deny", "review"] | None = None
    actual_policy: Literal["allow", "deny", "review"] | None = None
    trace_valid: bool = False
    required_evidence_ids: tuple[str, ...] = ()
    actual_evidence_ids: tuple[str, ...] = ()


class GradeFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: GradeStage
    passed: bool
    score: float = Field(ge=0, le=1)
    reasons: tuple[str, ...] = ()


class LayeredGradeReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["v1"] = "v1"
    case_id: str
    suite_version: str
    findings: tuple[GradeFinding, ...] = Field(min_length=1)

    @property
    def passed(self) -> bool:
        return all(finding.passed for finding in self.findings)


def grade_case(case: GradeCase) -> LayeredGradeReport:
    expected_retrieval = set(case.expected_retrieval_ids)
    actual_retrieval = set(case.actual_retrieval_ids)
    retrieval_reasons = []
    if expected_retrieval != actual_retrieval:
        missing = sorted(expected_retrieval - actual_retrieval)
        unexpected = sorted(actual_retrieval - expected_retrieval)
        if missing:
            retrieval_reasons.append(f"missing retrieval ids: {','.join(missing)}")
        if unexpected:
            retrieval_reasons.append(f"unexpected retrieval ids: {','.join(unexpected)}")

    findings = (
        GradeFinding(
            stage="retrieval", passed=not retrieval_reasons,
            score=1.0 if not retrieval_reasons else 0.0, reasons=tuple(retrieval_reasons),
        ),
        _exact_finding("intent", tuple(sorted(case.expected_metric_ids)) == tuple(sorted(case.actual_metric_ids)) and case.expected_dataset_id == case.actual_dataset_id, "metric or dataset intent differs"),
        _optional_exact_finding("ast", case.expected_ast_fingerprint, case.actual_ast_fingerprint),
        _optional_exact_finding("result", case.expected_result_fingerprint, case.actual_result_fingerprint),
        _optional_exact_finding("policy", case.expected_policy, case.actual_policy),
        _exact_finding("trace", case.trace_valid, "stored trace did not replay exactly"),
        _exact_finding(
            "evidence",
            set(case.required_evidence_ids).issubset(set(case.actual_evidence_ids)),
            "required evidence reference is missing",
        ),
    )
    return LayeredGradeReport(case_id=case.case_id, suite_version=case.suite_version, findings=findings)


def _exact_finding(stage: GradeStage, passed: bool, reason: str) -> GradeFinding:
    return GradeFinding(stage=stage, passed=passed, score=1.0 if passed else 0.0, reasons=() if passed else (reason,))


def _optional_exact_finding(stage: GradeStage, expected: str | None, actual: str | None) -> GradeFinding:
    if expected is None:
        return GradeFinding(stage=stage, passed=True, score=1.0)
    return _exact_finding(stage, expected == actual, f"expected {expected}, observed {actual}")
