"""V1 shadow adapter and privacy-safe comparison recorder (ADS-046).

In shadow mode the legacy v1 answer is produced and returned untouched. Afterwards the
governed graph analyses the same question, but only up to a compiled, estimated plan: its
`approve`, `execute`, `result_validate`, and `explain` nodes are replaced by blockers, and its
control store cannot create or resolve reviews. The recorded comparison holds fingerprints,
counts, semantic IDs, and stable codes only: no question text, SQL, parameters, or rows.
Because the governed side never executes, results are not compared, only whether each side
could answer and how their shapes line up.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from app.execution.result_validation import _canonical
from app.harness.graph import GraphNode
from app.runtime.analyze_service import StateFactory
from app.runtime.bootstrap import BootstrapRequest
from app.runtime.control_store import ControlStore, ControlStoreError
from app.runtime.graph_factory import governed_graph_v2
from app.runtime.graph_runner import AgentGraphRunner
from packages.platform_contracts.agent_runtime import AgentRunState, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics import AnalyticsQueryResponse
from packages.platform_contracts.routing import (
    RouteDecision,
    RoutingConfig,
    RoutingContext,
    RoutingRefusal,
    resolve_route,
)
from packages.platform_contracts.security import AnalyticsIdentity

BLOCKED_NODES = ("approve", "execute", "result_validate", "explain")
BLOCK_CODE = "shadow_execution_blocked"


class ShadowControlStore(ControlStore):
    """Control store view in which shadow runs can persist progress but never touch reviews."""

    def __init__(self, store: ControlStore) -> None:
        super().__init__(store.engine, lease_seconds=store.lease_seconds)

    def create_review(self, review) -> None:  # noqa: ANN001
        raise ControlStoreError("shadow runs cannot create reviews")

    def resolve_review(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise ControlStoreError("shadow runs cannot resolve reviews")

    def revise_review(self, *args, **kwargs):  # noqa: ANN002, ANN003
        raise ControlStoreError("shadow runs cannot revise reviews")


def shadow_nodes(nodes: Mapping[str, GraphNode]) -> dict[str, GraphNode]:
    """Replace every node that could execute or release a result with a failing blocker."""

    def blocker(node_input: NodeInput) -> NodeOutput:
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="failed",
            error=RunError(code=BLOCK_CODE, message_reference=f"{node_input.run_id}:{node_input.node_id}"),
        )

    return {**nodes, **{name: blocker for name in BLOCKED_NODES}}


NodeFactory = Callable[[AnalyticsIdentity, BootstrapRequest, ControlStore], Mapping[str, GraphNode]]
"""Builds the full governed node set; it must use the supplied (shadow-guarded) store for reviews."""


class LegacyFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["succeeded", "failed"]
    row_count: int
    column_count: int
    truncated: bool
    sql_fingerprint: str | None
    result_fingerprint: str | None


class GovernedFacts(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: Literal["plan_ready", "clarify", "refused", "review_required", "failed", "error", "timeout"]
    error_codes: list[str] = []
    contract: str | None = None
    intent_fingerprint: str | None = None
    metric_ids: list[str] = []
    dimension_ids: list[str] = []
    plan_reference: str | None = None
    estimated_cost_units: float | None = None
    policy_effect: str | None = None
    column_count: int | None = None


class ShadowComparison(BaseModel):
    """Everything recorded about one shadowed request; it is safe to log."""

    model_config = ConfigDict(extra="forbid")
    tenant_id: str
    request_id: str
    request_fingerprint: str
    legacy: LegacyFacts
    governed: GovernedFacts
    agreement: Literal["both_answerable", "legacy_only", "governed_only", "neither"]
    column_count_match: bool | None
    governed_executed: Literal[False] = False


Sink = Callable[[dict[str, Any]], None]


class InMemoryShadowRecorder:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def __call__(self, record: dict[str, Any]) -> None:
        self.records.append(record)


@dataclass
class ShadowRuntime:
    """Inert by default: with no analyzer or verifier the v1 endpoint behaves exactly as before."""

    config: RoutingConfig = field(default_factory=RoutingConfig)
    analyzer: "GovernedShadowAnalyzer | None" = None
    verifier: Any = None  # OIDCVerifier
    sink: Sink = field(default_factory=InMemoryShadowRecorder)
    timeout_seconds: float = 5.0

    def decide(self, authorization: str | None, purpose: str | None):
        """(decision, identity) for a verified caller routed to shadow, else None (plain legacy)."""
        if self.analyzer is None or self.verifier is None or not purpose:
            return None
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            return None
        try:
            identity = self.verifier.verify(token)
            if purpose not in identity.purposes:
                return None
            decision = resolve_route(
                self.config,
                RoutingContext(tenant_id=identity.tenant_id, request_id=uuid4().hex, purpose=purpose),
            )
        except Exception:  # noqa: BLE001 - anything unverifiable stays on the legacy path.
            return None
        return (decision, identity) if decision.mode == "shadow" else None


def require_shadow_decision(decision: RouteDecision) -> None:
    """The adapter only ever acts on a shadow route that forbids governed execution."""
    if decision.mode != "shadow" or decision.execute_governed or not decision.record_shadow:
        raise RoutingRefusal(f"shadow analysis is not permitted in {decision.mode} mode")


class GovernedShadowAnalyzer:
    def __init__(self, store: ControlStore, node_factory: NodeFactory, state_factory: StateFactory) -> None:
        self.store = ShadowControlStore(store)
        self.node_factory, self.state_factory = node_factory, state_factory

    def analyze(
        self, decision: RouteDecision, identity: AnalyticsIdentity, *, purpose: str, request_text: str
    ) -> GovernedFacts:
        require_shadow_decision(decision)
        if decision.tenant_id != identity.tenant_id or purpose not in identity.purposes:
            raise RoutingRefusal("shadow identity does not match the routed request")
        request = BootstrapRequest(request_id=decision.request_id, request_text=request_text, identity=identity)
        run_id = (
            "shadow-"
            + hashlib.sha256(f"{identity.tenant_id}:{purpose}:{decision.request_id}".encode()).hexdigest()[:24]
        )
        nodes = shadow_nodes(self.node_factory(identity, request, self.store))
        runner = AgentGraphRunner(self.store, governed_graph_v2(nodes))
        owner = f"shadow-{run_id}"
        state = runner.start(self.state_factory(request, run_id, purpose), owner_id=owner, lease_token=owner).state
        return _facts(state)


def _facts(state: AgentRunState) -> GovernedFacts:
    codes = [error.code for error in state.errors]
    intent = state.intent or {}
    contract = intent.get("semantic_contract") or {}
    cost = state.cost_decision or {}
    base = {
        "error_codes": codes,
        "contract": f"{contract['contract_id']}@{contract['contract_version']}" if contract else None,
        "intent_fingerprint": _digest(intent) if intent else None,
        "metric_ids": [m["metric_id"] for m in intent.get("metrics", [])],
        "dimension_ids": [g["dimension_id"] for g in intent.get("group_by", [])],
        "plan_reference": state.compiled_plan_reference,
        "estimated_cost_units": cost.get("estimated_cost_units"),
        "policy_effect": (state.policy_decision or {}).get("effect"),
        "column_count": len(intent.get("metrics", [])) + len(intent.get("group_by", [])) if intent else None,
    }
    if state.status == "waiting_approval":
        outcome = "clarify" if state.clarification_state else "review_required"
    elif BLOCK_CODE in codes and state.compiled_plan_reference:
        outcome = "plan_ready"
    elif "policy_denied" in codes:
        outcome = "refused"
    elif "review_creation_failed" in codes or "review_store_unavailable" in codes:
        outcome = "review_required"
    else:
        outcome = "failed"
    return GovernedFacts(outcome=outcome, **base)


def compare(
    *, tenant_id: str, request_id: str, request_text: str, legacy: AnalyticsQueryResponse, governed: GovernedFacts
) -> ShadowComparison:
    legacy_ok = legacy.status == "succeeded"
    governed_ok = governed.outcome == "plan_ready"
    agreement = (
        "both_answerable"
        if legacy_ok and governed_ok
        else "legacy_only"
        if legacy_ok
        else "governed_only"
        if governed_ok
        else "neither"
    )
    return ShadowComparison(
        tenant_id=tenant_id,
        request_id=request_id,
        request_fingerprint=hashlib.sha256(request_text.strip().encode()).hexdigest(),
        legacy=LegacyFacts(
            status=legacy.status,
            row_count=legacy.row_count,
            column_count=len(legacy.columns),
            truncated=legacy.truncated,
            sql_fingerprint=_digest(" ".join(legacy.sql.lower().split())) if legacy.sql else None,
            result_fingerprint=_digest(
                {
                    "columns": legacy.columns,
                    "rows": [[_canonical(row.get(c)) for c in legacy.columns] for row in legacy.rows],
                }
            )
            if legacy_ok
            else None,
        ),
        governed=governed,
        agreement=agreement,
        column_count_match=(len(legacy.columns) == governed.column_count)
        if legacy_ok and governed.column_count
        else None,
    )


async def query_with_shadow(
    legacy_call: Callable[[], Any],
    *,
    decision: RouteDecision,
    identity: AnalyticsIdentity,
    purpose: str,
    request_text: str,
    analyzer: GovernedShadowAnalyzer | None,
    sink: Sink,
    timeout_seconds: float = 5.0,
) -> AnalyticsQueryResponse:
    """Return the legacy response unchanged; shadow work happens after it and cannot fail the call."""
    if not decision.execute_legacy:
        raise RoutingRefusal("legacy execution is not permitted for this route")
    response: AnalyticsQueryResponse = await legacy_call()
    if not decision.record_shadow or analyzer is None:
        return response
    try:
        governed = await asyncio.wait_for(
            asyncio.to_thread(analyzer.analyze, decision, identity, purpose=purpose, request_text=request_text),
            timeout_seconds,
        )
    except asyncio.TimeoutError:
        governed = GovernedFacts(outcome="timeout")
    except Exception as exc:  # noqa: BLE001 - shadow failures are recorded, never surfaced.
        governed = GovernedFacts(outcome="error", error_codes=[type(exc).__name__])
    try:
        comparison = compare(
            tenant_id=decision.tenant_id,
            request_id=decision.request_id,
            request_text=request_text,
            legacy=response,
            governed=governed,
        )
        sink(comparison.model_dump(mode="json"))
    except Exception:  # noqa: BLE001 - a broken recorder must not affect the v1 response.
        pass
    return response


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()).hexdigest()
