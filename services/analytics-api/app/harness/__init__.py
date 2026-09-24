"""Provider fakes and deterministic scenario probes for local harness work."""

from app.harness.baseline import BaselineComparison, BaselineLock, BaselineLockError, ThresholdChangeApproval
from app.harness.fakes import (
    FakeCatalogProvider,
    FakeIdentityProvider,
    FakeModelProvider,
    FakePolicyProvider,
    FakeSemanticRegistryProvider,
    FakeWarehouseProvider,
)
from app.harness.faults import FaultPlan, FaultSpec
from app.harness.graders import GradeCase, GradeFinding, LayeredGradeReport, grade_case
from app.harness.graph import TERMINAL_NODE, GraphExecutionResult, GraphHarness, GraphHarnessError
from app.harness.node_contracts import (
    NodeConformanceReport,
    NodeConformanceResult,
    NodeContractError,
    NodeContractKit,
    NodeTimeoutError,
    TypedNodeError,
)
from app.harness.replay import build_deterministic_report
from app.harness.reports import render_json, render_junit, render_markdown, write_report_artifacts
from app.harness.trace import CapturedTrace, TraceReplayError, redact_payload

__all__ = [
    "FakeCatalogProvider", "FakeIdentityProvider", "FakeModelProvider",
    "FakePolicyProvider", "FakeSemanticRegistryProvider", "FakeWarehouseProvider",
    "GraphExecutionResult", "GraphHarness", "GraphHarnessError", "TERMINAL_NODE",
    "FaultPlan", "FaultSpec", "NodeConformanceReport", "NodeConformanceResult",
    "NodeContractError", "NodeContractKit", "NodeTimeoutError", "TypedNodeError",
    "CapturedTrace", "TraceReplayError", "redact_payload", "GradeCase", "GradeFinding",
    "LayeredGradeReport", "grade_case", "render_json", "render_junit", "render_markdown",
    "write_report_artifacts", "BaselineComparison", "BaselineLock", "BaselineLockError",
    "ThresholdChangeApproval",
    "build_deterministic_report",
]
