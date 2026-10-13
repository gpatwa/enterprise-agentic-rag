"""Wrappers that add tracing, metrics, and logs around the API, graph nodes, context, gateway, and evidence (ADS-065).

They are proxies: the governed code is not modified and does not know it is observed. Each wrapper reads only IDs, codes, and
counts from what it wraps (never the request text, rows, SQL, or tokens).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from app.observability.core import Observability, run_ref, trace_id_for_run
from app.runtime.analyze_service import GovernedAnalyzeService, ServiceError
from packages.platform_contracts.security import AnalyticsIdentity

# The node that retrieves certified context is reported as the context layer; every other node is the graph layer.
CONTEXT_NODES = frozenset({"retrieve"})


def _outcome(response: Any) -> str:
    outcome = getattr(response, "outcome", None)
    return getattr(outcome, "outcome", None) or getattr(response, "state", "unknown")


class TracedService:
    """The API layer: one span per operation, in the trace of the run it touches."""

    def __init__(self, service: GovernedAnalyzeService, obs: Observability) -> None:
        self._service, self._obs = service, obs

    def __getattr__(self, name: str) -> Any:  # anything not instrumented passes straight through
        return getattr(self._service, name)

    def _run(self, op: str, identity: AnalyticsIdentity, run_id: str, purpose: str, call: Callable[[], Any]) -> Any:
        obs = self._obs
        started = time.perf_counter()
        with obs.tracer.span(
            f"api.{op}",
            "api",
            trace_id=trace_id_for_run(identity.tenant_id, run_id),
            op=op,
            run_ref=run_ref(run_id),
            tenant_id=identity.tenant_id,
        ) as span:
            try:
                response = call()
            except ServiceError as exc:
                obs.tracer.annotate(span, error_code=exc.code, outcome="error")
                span.status = "error"
                obs.metrics.inc(
                    "analytics_requests_total", op=op, outcome="error", error_code=exc.code, tenant=identity.tenant_id
                )
                obs.log.emit("warning", "request_refused", op=op, error_code=exc.code, run_ref=run_ref(run_id))
                raise
            outcome = _outcome(response)
            obs.tracer.annotate(span, outcome=outcome, state=response.state)
            obs.metrics.inc("analytics_requests_total", op=op, outcome=outcome, tenant=identity.tenant_id)
            obs.metrics.observe("analytics_request_seconds", time.perf_counter() - started, op=op)
            obs.log.emit(
                "info", "request_completed", op=op, outcome=outcome, state=response.state, run_ref=run_ref(run_id)
            )
            return response

    def analyze(self, identity, *, purpose, idempotency_key, request_text):
        run_id = self._service.run_id_for(identity, purpose, idempotency_key)
        return self._run(
            "analyze",
            identity,
            run_id,
            purpose,
            lambda: self._service.analyze(
                identity, purpose=purpose, idempotency_key=idempotency_key, request_text=request_text
            ),
        )

    def status(self, identity, *, purpose, run_id):
        return self._run(
            "status", identity, run_id, purpose, lambda: self._service.status(identity, purpose=purpose, run_id=run_id)
        )

    def clarify(self, identity, *, purpose, run_id, ambiguity_code, selected_id):
        return self._run(
            "clarify",
            identity,
            run_id,
            purpose,
            lambda: self._service.clarify(
                identity, purpose=purpose, run_id=run_id, ambiguity_code=ambiguity_code, selected_id=selected_id
            ),
        )

    def decide_review(self, identity, *, purpose, run_id, decision, plan_fingerprint, note):
        return self._run(
            "review",
            identity,
            run_id,
            purpose,
            lambda: self._service.decide_review(
                identity,
                purpose=purpose,
                run_id=run_id,
                decision=decision,
                plan_fingerprint=plan_fingerprint,
                note=note,
            ),
        )


def traced_node(node_id: str, handler: Callable[[Any], Any], obs: Observability) -> Callable[[Any], Any]:
    """The graph (and context) layer: one span per node execution, in the run's trace."""
    layer = "context" if node_id in CONTEXT_NODES else "graph"

    def handle(node_input: Any) -> Any:
        started = time.perf_counter()
        with obs.tracer.span(
            f"{layer}.{node_id}",
            layer,
            trace_id=trace_id_for_run(node_input.tenant_id, node_input.run_id),
            node_id=node_id,
            run_ref=run_ref(node_input.run_id),
            tenant_id=node_input.tenant_id,
        ) as span:
            output = handler(node_input)
            error = getattr(getattr(output, "error", None), "code", None)
            obs.tracer.annotate(span, status=output.status, next_node=output.next_node, error_code=error)
            if output.status == "failed":
                span.status = "error"
            obs.metrics.inc("analytics_node_total", node=node_id, outcome=output.status, layer=layer)
            obs.metrics.observe("analytics_node_seconds", time.perf_counter() - started, node=node_id)
            if error:
                obs.log.emit(
                    "warning", "node_failed", node_id=node_id, error_code=error, run_ref=run_ref(node_input.run_id)
                )
            return output

    return handle


class TracedGateway:
    """The gateway layer: spans for estimate and execute, with counts and cost only."""

    def __init__(self, gateway: Any, obs: Observability) -> None:
        self._gateway, self._obs = gateway, obs
        self.dialect = gateway.dialect

    def __getattr__(self, name: str) -> Any:
        return getattr(self._gateway, name)

    def estimate(self, plan: Any) -> float:
        with self._obs.tracer.span("gateway.estimate", "gateway", dialect=self.dialect) as span:
            cost = self._gateway.estimate(plan)
            self._obs.tracer.annotate(span, cost_units=float(cost))
            return cost

    def execute(self, plan: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        with self._obs.tracer.span("gateway.execute", "gateway", dialect=self.dialect) as span:
            try:
                result = self._gateway.execute(plan, **kwargs)
            except Exception as exc:
                code = getattr(exc, "code", type(exc).__name__)
                self._obs.tracer.annotate(span, error_code=code)
                self._obs.metrics.inc("analytics_gateway_total", dialect=self.dialect, outcome="error", error_code=code)
                raise
            self._obs.tracer.annotate(
                span,
                row_count=result.row_count,
                byte_count=result.byte_count,
                truncated=result.truncated,
                cost_units=float(result.estimated_cost_units),
            )
            self._obs.metrics.inc("analytics_gateway_total", dialect=self.dialect, outcome="ok")
            self._obs.metrics.observe("analytics_gateway_seconds", time.perf_counter() - started, dialect=self.dialect)
            return result


class TracedEvidenceStore:
    """The evidence layer: a span around sealing and reading, with the chain position only."""

    def __init__(self, store: Any, obs: Observability) -> None:
        self._store, self._obs = store, obs

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def append(self, envelope: Any) -> Any:
        with self._obs.tracer.span(
            "evidence.seal",
            "evidence",
            trace_id=trace_id_for_run(envelope.tenant_id, envelope.run_id),
            run_ref=run_ref(envelope.run_id),
            terminal_kind=envelope.terminal_kind,
            tenant_id=envelope.tenant_id,
        ) as span:
            appended = self._store.append(envelope)
            self._obs.tracer.annotate(span, chain_seq=appended.chain_seq)
            self._obs.metrics.inc("analytics_evidence_sealed_total", outcome=envelope.terminal_kind)
            return appended
