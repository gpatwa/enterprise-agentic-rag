"""Read-only execution gateways for certified, compiled analytical queries."""

from app.execution.bridge import ExecutionResultStore, GatewayCostEstimator, GatewayExecutor
from app.execution.duckdb_gateway import DuckDBGateway
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
from app.execution.validation import validate_read_only_sql

__all__ = [
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
    "validate_read_only_sql",
]
