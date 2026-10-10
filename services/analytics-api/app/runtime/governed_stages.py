"""Compile, authorize, and estimate nodes used by the governed graph."""

from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol
from uuid import uuid4

from app.compiler.service import CertifiedIntentCompiler
from app.security.authorization import authorize
from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.analytics_planning import DurableReviewDecision
from packages.platform_contracts.security import AnalyticsIdentity


class CompiledPlanStore:
    """Process-local demo store; production durable plan storage belongs to ADS-040+."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._plans: dict[tuple[str, str, str], Any] = {}

    def put(self, tenant_id: str, run_id: str, plan: Any) -> str:
        sql = getattr(plan, "sql", repr(plan))
        reference = hashlib.sha256(f"{tenant_id}:{run_id}:{sql}".encode()).hexdigest()
        with self._lock:
            self._plans[(tenant_id, run_id, reference)] = plan
        return reference

    def get(self, tenant_id: str, run_id: str, reference: str) -> Any:
        with self._lock:
            try:
                return self._plans[(tenant_id, run_id, reference)]
            except KeyError as exc:
                raise LookupError("compiled plan reference is not scoped to this run") from exc


class PolicyValueStore:
    """Short-lived local handoff for sensitive policy values; values never enter run state."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._values: dict[tuple[str, str, str], dict[str, Any]] = {}

    def put(self, tenant_id: str, run_id: str, values: dict[str, Any]) -> str:
        reference = uuid4().hex
        with self._lock:
            self._values[(tenant_id, run_id, reference)] = dict(values)
        return reference

    def get(self, tenant_id: str, run_id: str, reference: str) -> dict[str, Any]:
        with self._lock:
            try:
                return self._values.pop((tenant_id, run_id, reference))
            except KeyError as exc:
                raise LookupError("policy values are not scoped to this run") from exc


class CostEstimator(Protocol):
    def estimate(self, compiled_plan: Any) -> float: ...


def compile_node(compiler: CertifiedIntentCompiler, plans: CompiledPlanStore, policy_values: PolicyValueStore):
    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            decision = node_input.payload.get("policy_decision") or {}
            if decision.get("effect") != "allow":
                raise ValueError("only an explicit policy allow can reach compilation")
            values = policy_values.get(
                node_input.tenant_id,
                node_input.run_id,
                decision.get("policy_values_reference", ""),
            )
            compiled = compiler.compile(intent, policy_values=values)
            reference = plans.put(node_input.tenant_id, node_input.run_id, compiled)
        except Exception as exc:  # noqa: BLE001 - compiler errors stop before authorization or execution.
            return _failure(node_input, "compile_failed", type(exc).__name__)
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="estimate",
            payload={"compiled_plan_reference": reference},
            evidence=(_evidence(f"compile:{reference}", reference),),
        )

    return handle


def analytics_plan_node(contracts):
    """Emit provenance citations for the exact certified intent selected by prior nodes."""

    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            document = contracts.get_certified(
                intent.semantic_contract.contract_id,
                intent.semantic_contract.contract_version,
            )
            intent.validate_against(document.contract)
            if document.contract.tenant_id != node_input.tenant_id:
                raise ValueError("tenant mismatch")
        except Exception as exc:  # noqa: BLE001 - no plan proceeds without exact certified provenance.
            return _failure(node_input, "plan_validation_failed", type(exc).__name__)
        selected = [intent.dataset_id, *(item.metric_id for item in intent.metrics)]
        selected += [item.dimension_id for item in intent.group_by]
        selected += [item.field_id for item in intent.filters]
        if intent.time_range:
            selected.append(intent.time_range.dimension_id)
        evidence = tuple(
            _evidence(
                f"semantic-reference:{intent.semantic_contract.contract_id}:{identifier}",
                f"{intent.semantic_contract.contract_version}:{identifier}",
            )
            for identifier in selected
        )
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="validate",
            evidence=evidence,
        )

    return handle


def fake_execution_node(executor):
    """Inject a local fake executor; this M3 helper cannot construct a live adapter."""

    def handle(node_input: NodeInput) -> NodeOutput:
        reference = node_input.payload.get("compiled_plan_reference")
        approval = node_input.payload.get("approval_state") or {}
        if not reference:
            return _failure(node_input, "compiled_plan_missing", "execution requires a compiled plan")
        if approval.get("state") not in {"approved", None}:
            return _failure(node_input, "execution_not_approved", "approved state is required")
        try:
            result_reference = executor.execute(
                tenant_id=node_input.tenant_id,
                run_id=node_input.run_id,
                plan_reference=reference,
            )
        except Exception as exc:  # noqa: BLE001 - fake action errors become typed failures.
            return _failure(node_input, "fake_execution_failed", type(exc).__name__)
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="result_validate",
            payload={"execution_reference": str(result_reference)},
            evidence=(_evidence(f"fake-execution:{node_input.run_id}", str(result_reference)),),
        )

    return handle


def policy_node(
    contracts,
    identity: AnalyticsIdentity,
    policy_values: PolicyValueStore,
    *,
    review_store=None,
    review_ttl: timedelta = timedelta(hours=4),
):
    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            contract = contracts.get_certified(
                intent.semantic_contract.contract_id,
                intent.semantic_contract.contract_version,
            ).contract
            targets = {intent.dataset_id, *(item.metric_id for item in intent.metrics)}
            targets.update(item.dimension_id for item in intent.group_by)
            targets.update(item.field_id for item in intent.filters)
            if intent.time_range:
                targets.add(intent.time_range.dimension_id)
            decision = authorize(identity, contract, targets, node_input.purpose)
            if identity.tenant_id != node_input.tenant_id:
                raise ValueError("identity tenant mismatch")
            if node_input.purpose not in identity.purposes:
                raise ValueError("identity purpose is not authorized")
        except Exception as exc:  # noqa: BLE001 - policy inputs fail closed.
            return _failure(node_input, "policy_evaluation_failed", type(exc).__name__)
        payload = {"policy_decision": decision.model_dump(mode="json")}
        if decision.effect == "deny":
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                payload=payload,
                error=RunError(code="policy_denied", message_reference=f"policy:{decision.decision_id}"),
                evidence=(_evidence(f"policy-deny:{decision.policy_version}", decision.decision_id),),
            )
        if decision.effect == "review":
            if review_store is None:
                return _failure(node_input, "review_store_unavailable", "policy review is required")
            now = datetime.now(timezone.utc)
            fingerprint = hashlib.sha256(intent.model_dump_json().encode()).hexdigest()
            review_id = hashlib.sha256(f"{node_input.run_id}:policy:{fingerprint}".encode()).hexdigest()
            review = DurableReviewDecision(
                review_id=review_id,
                run_id=node_input.run_id,
                tenant_id=node_input.tenant_id,
                purpose=node_input.purpose,
                plan_fingerprint=fingerprint,
                requested_by=identity.user_id,
                created_at=now,
                expires_at=now + review_ttl,
            )
            try:
                review_store.create_review(review)
            except Exception as exc:  # noqa: BLE001 - the graph cannot skip required human review.
                return _failure(node_input, "review_creation_failed", type(exc).__name__)
            payload["approval_state"] = {
                "review_id": review_id,
                "state": "pending",
                "plan_fingerprint": fingerprint,
                "reason": "policy_review",
                "review_kind": "policy_review",
            }
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="waiting",
                next_node="approve",
                payload=payload,
                evidence=(_evidence(f"policy-review:{review_id}", fingerprint),),
            )
        values: dict[str, Any] = {}
        filters_by_id = {item.id: item for item in contract.filters}
        required_filter_ids = set(decision.enforced_filter_ids)
        selected_metrics = {metric.metric_id for metric in intent.metrics}
        required_filter_ids.update(
            filter_id
            for metric in contract.metrics
            if metric.id in selected_metrics
            for filter_id in metric.required_filter_ids
        )
        try:
            for filter_id in required_filter_ids:
                required_filter = filters_by_id[filter_id]
                if required_filter.value_source == "literal":
                    value = required_filter.literal_value
                elif required_filter.value_source == "identity_claim":
                    value = identity.claims.get(filter_id)
                else:
                    value = None
                if value is None:
                    raise ValueError(f"missing required value for policy filter {filter_id}")
                values[filter_id] = value
            values_ref = policy_values.put(node_input.tenant_id, node_input.run_id, values)
        except Exception as exc:  # noqa: BLE001 - missing mandatory row filters deny the request.
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                error=RunError(code="policy_denied", message_reference=f"policy-filter:{type(exc).__name__}"),
                evidence=(_evidence(f"policy-filter-deny:{node_input.run_id}", type(exc).__name__),),
            )
        payload["policy_decision"].update({"policy_values_reference": values_ref})
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="compile",
            payload=payload,
            evidence=(_evidence(f"policy-allow:{decision.policy_version}", decision.decision_id),),
        )

    return handle


def estimate_node(
    plans: CompiledPlanStore,
    estimator: CostEstimator,
    *,
    approval_threshold: float,
    review_store=None,
    requested_by: str | None = None,
    review_ttl: timedelta = timedelta(hours=4),
):
    if approval_threshold <= 0:
        raise ValueError("approval threshold must be positive")

    def handle(node_input: NodeInput) -> NodeOutput:
        reference = node_input.payload.get("compiled_plan_reference")
        try:
            plan = plans.get(node_input.tenant_id, node_input.run_id, reference)
            cost = estimator.estimate(plan)
            if not isinstance(cost, (int, float)) or cost < 0:
                raise ValueError("estimator returned an invalid cost")
        except Exception as exc:  # noqa: BLE001 - unknown estimates cannot execute.
            return _failure(node_input, "estimate_failed", type(exc).__name__)
        if cost > node_input.remaining_budget.max_cost_units:
            return _failure(node_input, "cost_budget_exceeded", "estimate exceeds run budget")
        requires_approval = cost >= approval_threshold
        decision = {
            "estimated_cost_units": float(cost),
            "requires_approval": requires_approval,
            "reason": "cost_threshold" if cost >= approval_threshold else None,
        }
        target = "approve" if decision["requires_approval"] else "execute"
        evidence = _evidence(f"estimate:{reference}:{cost}", str(cost))
        approval_state = None
        status = "completed"
        if requires_approval:
            if review_store is None or not requested_by:
                return _failure(
                    node_input,
                    "review_store_unavailable",
                    "human approval requires durable storage and requester identity",
                )
            now = datetime.now(timezone.utc)
            review_id = hashlib.sha256(f"{node_input.run_id}:{reference}".encode()).hexdigest()
            review = DurableReviewDecision(
                review_id=review_id,
                run_id=node_input.run_id,
                tenant_id=node_input.tenant_id,
                purpose=node_input.purpose,
                plan_fingerprint=reference,
                requested_by=requested_by,
                created_at=now,
                expires_at=now + review_ttl,
            )
            try:
                review_store.create_review(review)
            except Exception as exc:  # noqa: BLE001 - no review means no pause or execution.
                return _failure(node_input, "review_creation_failed", type(exc).__name__)
            approval_state = {
                "review_id": review_id,
                "state": "pending",
                "plan_fingerprint": reference,
                "reason": "human_approval",
                "review_kind": "cost_threshold",
            }
            status = "waiting"
        payload = {"cost_decision": decision}
        if approval_state is not None:
            payload["approval_state"] = approval_state
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status=status,
            next_node=target,
            payload=payload,
            evidence=(evidence,),
        )

    return handle


def review_decision_node(review_store):
    def handle(node_input: NodeInput) -> NodeOutput:
        approval = node_input.payload.get("approval_state") or {}
        review_id = approval.get("review_id")
        if not review_id:
            return _failure(node_input, "review_reference_missing", "approval state has no review ID")
        try:
            review = review_store.get_review(review_id, tenant_id=node_input.tenant_id, purpose=node_input.purpose)
        except Exception as exc:  # noqa: BLE001 - unknown review state is a hard stop.
            return _failure(node_input, "review_lookup_failed", type(exc).__name__)
        if review.run_id != node_input.run_id or review.plan_fingerprint != approval.get("plan_fingerprint"):
            return _failure(node_input, "stale_approval", "review no longer binds to this run and plan")
        if review.state == "approved":
            if approval.get("review_kind") in {"semantic_exploration", "policy_review"}:
                return NodeOutput(
                    run_id=node_input.run_id,
                    node_id=node_input.node_id,
                    status="failed",
                    error=RunError(
                        code="stale_context",
                        message_reference=f"review:{review.review_id}:manual_semantic_certification_required",
                    ),
                    evidence=(
                        _evidence(
                            f"exploration-reviewed:{review.review_id}",
                            review.plan_fingerprint,
                        ),
                    ),
                )
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="completed",
                next_node="execute",
                payload={"approval_state": {**approval, "state": "approved", "reviewer_id": review.resolved_by}},
                evidence=(_evidence(f"review-approved:{review.review_id}:{review.revision}", review.plan_fingerprint),),
            )
        reason = (
            "review_rejected"
            if review.state == "rejected"
            else "review_expired"
            if review.state == "expired"
            else "review_not_approved"
        )
        code = "policy_denied" if review.state == "rejected" else "stale_context"
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="failed",
            error=RunError(code=code, message_reference=f"review:{review.review_id}:{reason}"),
            evidence=(_evidence(reason, review.plan_fingerprint),),
        )

    return handle


def _failure(node_input: NodeInput, code: str, reference: str) -> NodeOutput:
    return NodeOutput(
        run_id=node_input.run_id,
        node_id=node_input.node_id,
        status="failed",
        error=RunError(code=code, message_reference=f"{node_input.run_id}:{reference}"),
        evidence=(_evidence(f"{code}:{reference}", reference),),
    )


def _evidence(value: str, fingerprint_source: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"stage:{hashlib.sha256(value.encode()).hexdigest()[:32]}",
        kind="decision",
        fingerprint=hashlib.sha256(fingerprint_source.encode()).hexdigest(),
    )
