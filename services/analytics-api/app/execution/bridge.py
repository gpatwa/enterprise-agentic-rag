"""Adapters that let the governed graph's executor and estimator slots use real gateways."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from typing import Any

from app.execution.gateway import ExecutionGateway, ExecutionLimits, ExecutionResult
from app.runtime.bounded import BoundedDict


class ExecutionResultStore:
    """Process-local, run-scoped result handoff. Rows are never stored durably.

    With an engine it records which plan produced each result, and `resume` (used only by the in-flight nodes that need the rows,
    never by a status read) rebuilds a missing result by running the stored plan again through the executor that registered itself.
    """

    def __init__(self, engine: Any = None) -> None:
        self._lock = threading.Lock()
        self._results: BoundedDict = BoundedDict()
        self._engine = engine
        # tenant id -> callable(tenant_id, run_id, plan_reference) -> ExecutionResult. Keyed by tenant so a rebuild can only run on
        # the gateways of the tenant whose run it is (a single shared hook could run one tenant's SQL on another's warehouse).
        self._rebuilders: dict[str, Any] = {}

    def register_rebuilder(self, tenant_id: str, rebuild: Any) -> None:
        with self._lock:
            self._rebuilders[tenant_id] = rebuild

    @staticmethod
    def reference_for(tenant_id: str, run_id: str, plan_reference: str) -> str:
        return hashlib.sha256(f"{tenant_id}:{run_id}:{plan_reference}:result".encode()).hexdigest()

    def has(self, tenant_id: str, run_id: str, reference: str) -> bool:
        with self._lock:
            return (tenant_id, run_id, reference) in self._results

    def put(self, tenant_id: str, run_id: str, plan_reference: str, result: ExecutionResult) -> str:
        reference = self.reference_for(tenant_id, run_id, plan_reference)
        with self._lock:
            self._results[(tenant_id, run_id, reference)] = result
        if self._engine is not None:
            from app.runtime.governed_stages import _insert_once

            _insert_once(
                self._engine,
                "analytics_run_result_links",
                {"tenant_id": tenant_id, "run_id": run_id, "result_reference": reference},
                {"plan_reference": plan_reference},
            )
        return reference

    def get(self, tenant_id: str, run_id: str, reference: str) -> ExecutionResult:
        with self._lock:
            try:
                return self._results[(tenant_id, run_id, reference)]
            except KeyError as exc:
                raise LookupError("execution result is not scoped to this run") from exc

    def resume(self, tenant_id: str, run_id: str, reference: str) -> ExecutionResult:
        """`get`, but an in-flight run whose process died runs its stored plan again to rebuild the rows."""
        try:
            return self.get(tenant_id, run_id, reference)
        except LookupError:
            with self._lock:
                rebuild = self._rebuilders.get(tenant_id)
            if self._engine is None or rebuild is None:
                raise
            from app.runtime.governed_stages import _load

            plan_reference = _load(
                self._engine, "analytics_run_result_links", "plan_reference", tenant_id, run_id, reference
            )
            if plan_reference is None:
                raise
            result = rebuild(tenant_id, run_id, plan_reference)
            with self._lock:
                self._results[(tenant_id, run_id, reference)] = result
            return result


class GatewayExecutor:
    """Satisfies the `executor.execute(...)` contract used by the graph execution node."""

    def __init__(
        self,
        plans: Any,
        gateways: Mapping[str, ExecutionGateway],
        results: ExecutionResultStore,
        limits: ExecutionLimits,
        *,
        tenant_id: str | None = None,
    ) -> None:
        self._plans = plans
        self._gateways = dict(gateways)
        self._results = results
        self._limits = limits
        if tenant_id is not None and hasattr(results, "register_rebuilder"):
            results.register_rebuilder(tenant_id, self._rebuild)

    def _rebuild(self, tenant_id: str, run_id: str, plan_reference: str) -> ExecutionResult:
        plan = self._plans.get(tenant_id, run_id, plan_reference)
        return _gateway_for(self._gateways, plan).execute(plan, limits=self._limits)

    def execute(self, *, tenant_id: str, run_id: str, plan_reference: str) -> str:
        reference = self._results.reference_for(tenant_id, run_id, plan_reference)
        if self._results.has(tenant_id, run_id, reference):
            return reference  # a resumed worker must not run the same query again: the earlier worker's result is kept
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
