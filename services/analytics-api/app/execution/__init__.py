"""Read-only execution gateways for certified, compiled analytical queries."""

from app.execution.bridge import ExecutionResultStore, GatewayCostEstimator, GatewayExecutor
from app.execution.duckdb_gateway import DuckDBGateway
from app.execution.explanation import (
    DraftClaim,
    Explanation,
    ExplanationIntegrityError,
    FactSheet,
    VisualizationSpec,
    build_fact_sheet,
    explain_result,
    verify_claims,
    visualization_spec,
)
from app.execution.gateway import (
    CancellationToken,
    CostLimitExceeded,
    DialectMismatch,
    ExecutionCancelled,
    ExecutionError,
    ExecutionGateway,
    ExecutionLimits,
    ExecutionResult,
    ExecutionTimeout,
    QueryRejected,
)
from app.execution.postgres_gateway import PostgresGateway
from app.execution.result_validation import (
    ResultIssue,
    ResultValidationReport,
    control_intent,
    plan_fingerprint,
    result_fingerprint,
    run_control_totals,
    validate_result,
)
from app.execution.validation import validate_read_only_sql

__all__ = [
    "DraftClaim",
    "Explanation",
    "ExplanationIntegrityError",
    "FactSheet",
    "VisualizationSpec",
    "build_fact_sheet",
    "explain_result",
    "verify_claims",
    "visualization_spec",
    "CancellationToken",
    "CostLimitExceeded",
    "DialectMismatch",
    "DuckDBGateway",
    "ExecutionCancelled",
    "ExecutionResultStore",
    "GatewayCostEstimator",
    "GatewayExecutor",
    "ExecutionError",
    "ExecutionGateway",
    "ExecutionLimits",
    "ExecutionResult",
    "ExecutionTimeout",
    "PostgresGateway",
    "QueryRejected",
    "ResultIssue",
    "ResultValidationReport",
    "control_intent",
    "plan_fingerprint",
    "result_fingerprint",
    "run_control_totals",
    "validate_result",
    "validate_read_only_sql",
]
