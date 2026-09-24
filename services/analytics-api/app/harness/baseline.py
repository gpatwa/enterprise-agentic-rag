"""Immutable evaluation baseline lock and threshold-change policy."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.harness.graders import GradeStage, LayeredGradeReport


class BaselineLockError(ValueError):
    """Raised when a candidate baseline weakens or replaces a locked gate."""


class ThresholdChangeApproval(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    approval_id: str = Field(min_length=1, max_length=255)
    baseline_id: str = Field(min_length=1, max_length=255)
    reviewer: str = Field(min_length=1, max_length=255)
    rationale: str = Field(min_length=10, max_length=2_000)
    approved_at: datetime


class BaselineLock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    lock_version: Literal["v1"] = "v1"
    baseline_id: str = Field(min_length=1, max_length=255)
    suite_version: str = Field(min_length=1, max_length=255)
    fixture_digest: str = Field(min_length=1, max_length=255)
    thresholds: dict[GradeStage, float]

    def digest(self) -> str:
        canonical = json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode()).hexdigest()

    def compare(self, report: LayeredGradeReport) -> "BaselineComparison":
        regressions: list[str] = []
        stage_results: list[StageThresholdResult] = []
        findings = {finding.stage: finding for finding in report.findings}
        for stage, threshold in self.thresholds.items():
            finding = findings.get(stage)
            score = finding.score if finding is not None else 0.0
            passed = score >= threshold
            stage_results.append(StageThresholdResult(stage=stage, score=score, threshold=threshold, passed=passed))
            if not passed:
                reason = "stage missing from report" if finding is None else f"score {score:.3f} below locked threshold {threshold:.3f}"
                regressions.append(f"{stage} {reason}")
        return BaselineComparison(
            baseline_id=self.baseline_id,
            report_case_id=report.case_id,
            report_version=report.report_version,
            regressions=tuple(regressions),
            stages=tuple(stage_results),
            blocked=bool(regressions),
        )

    def validate_candidate(self, candidate: "BaselineLock", approval: ThresholdChangeApproval | None = None) -> None:
        changed = (
            candidate.suite_version != self.suite_version
            or candidate.fixture_digest != self.fixture_digest
            or candidate.thresholds != self.thresholds
        )
        if not changed:
            return
        if approval is None or approval.baseline_id != self.baseline_id:
            raise BaselineLockError("baseline or threshold change requires independent approval")
        if approval.approved_at.tzinfo is None:
            raise BaselineLockError("baseline approval timestamp must include a timezone")


class StageThresholdResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: GradeStage
    score: float = Field(ge=0, le=1)
    threshold: float = Field(ge=0, le=1)
    passed: bool


class BaselineComparison(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    baseline_id: str
    report_case_id: str
    report_version: str
    regressions: tuple[str, ...] = ()
    stages: tuple[StageThresholdResult, ...] = ()
    blocked: bool = False


def load_baseline(path: str | Path) -> BaselineLock:
    return BaselineLock.model_validate_json(Path(path).read_text())
