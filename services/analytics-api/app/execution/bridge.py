"""Adapters that let the governed graph's executor and estimator slots use real gateways."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from typing import Any

from app.execution.gateway import ExecutionGateway, ExecutionLimits, ExecutionResult


class ExecutionResultStore:
    """Process-local, run-scoped result handoff; durable evidence storage is ADS-042."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._results: dict[tuple[str, str, str], ExecutionResult] = {}

    def put(self, tenant_id: str, run_id: str, plan_reference: str, result: ExecutionResult) -> str:
        reference = hashlib.sha256(f"{tenant_id}:{run_id}:{plan_reference}:result".encode()).hexdigest()
        with self._lock:
            self._results[(tenant_id, run_id, reference)] = result
        return reference

    def get(self, tenant_id: str, run_id: str, reference: str) -> ExecutionResult:
        with self._lock:
            try:
                return self._results[(tenant_id, run_id, reference)]
            except KeyError as exc:
                raise LookupError("execution result is not scoped to this run") from exc


class GatewayExecutor:
    """Satisfies the `executor.execute(...)` contract used by the graph execution node."""

    def __init__(
        self,
        plans: Any,
        gateways: Mapping[str, ExecutionGateway],
        results: ExecutionResultStore,
        limits: ExecutionLimits,
    ) -> None:
        self._plans = plans
        self._gateways = dict(gateways)
        self._results = results
        self._limits = limits

    def execute(self, *, tenant_id: str, run_id: str, plan_reference: str) -> str:
        plan = self._plans.get(tenant_id, run_id, plan_reference)
        result = _gateway_for(self._gateways, plan).execute(plan, limits=self._limits)
        return self._results.put(tenant_id, run_id, plan_reference, result)


class GatewayCostEstimator:
    """Satisfies `CostEstimator`; cost units are the owning gateway's, per dialect."""

    def __init__(self, gateways: Mapping[str, ExecutionGateway]) -> None:
        self._gateways = dict(gateways)

    def estimate(self, compiled_plan: Any) -> float:
        return _gateway_for(self._gateways, compiled_plan).estimate(compiled_plan)


def _gateway_for(gateways: Mapping[str, ExecutionGateway], plan: Any) -> ExecutionGateway:
    try:
        return gateways[plan.dialect]
    except (KeyError, AttributeError) as exc:
        raise LookupError("no execution gateway is registered for the plan dialect") from exc
