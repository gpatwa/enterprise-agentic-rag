"""Exact-version semantic certification gate before automatic compilation."""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.analytics_planning import DurableReviewDecision


def certified_intent_node(
    registry,
    *,
    review_store=None,
    requested_by: str | None = None,
    review_ttl: timedelta = timedelta(hours=4),
):
    def handle(node_input: NodeInput) -> NodeOutput:
        intent = None
        try:
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            if intent.tenant_id != node_input.tenant_id:
                return _failure(node_input, "certification:tenant_mismatch")
            document = registry.get_certified(
                intent.semantic_contract.contract_id,
                intent.semantic_contract.contract_version,
            )
            intent.validate_against(document.contract)
            if document.contract.tenant_id != node_input.tenant_id:
                return _failure(node_input, "certification:contract_tenant_mismatch")
        except Exception as exc:  # noqa: BLE001 - uncertified meaning branches to review, never compilation.
            reason = f"certification:{type(exc).__name__}"
            fingerprint = hashlib.sha256(
                intent.model_dump_json().encode() if intent is not None else reason.encode()
            ).hexdigest()
            if review_store is not None and requested_by and intent is not None:
                now = datetime.now(timezone.utc)
                review_id = hashlib.sha256(f"{node_input.run_id}:explore:{fingerprint}".encode()).hexdigest()
                review = DurableReviewDecision(
                    review_id=review_id,
                    run_id=node_input.run_id,
                    tenant_id=node_input.tenant_id,
                    purpose=node_input.purpose,
                    plan_fingerprint=fingerprint,
                    requested_by=requested_by,
                    created_at=now,
                    expires_at=now + review_ttl,
                )
                try:
                    review_store.create_review(review)
                except Exception as review_exc:  # noqa: BLE001 - do not silently skip independent review.
                    return _failure(node_input, f"review_creation:{type(review_exc).__name__}")
                return NodeOutput(
                    run_id=node_input.run_id,
                    node_id=node_input.node_id,
                    status="waiting",
                    next_node="approve",
                    payload={
                        "approval_state": {
                            "review_id": review_id,
                            "state": "pending",
                            "plan_fingerprint": fingerprint,
                            "reason": "uncertified_exploration",
                            "review_kind": "semantic_exploration",
                        }
                    },
                    evidence=(_evidence(review_id, fingerprint),),
                )
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                payload={"approval_state": {"required": True, "reason": "uncertified_intent"}},
                error=RunError(code="stale_context", message_reference=reason),
                evidence=(
                    EvidenceReference(
                        evidence_id=f"certification:{node_input.run_id}",
                        kind="decision",
                        fingerprint=fingerprint,
                    ),
                ),
            )
        fingerprint = hashlib.sha256(
            f"{intent.semantic_contract.contract_id}@{intent.semantic_contract.contract_version}".encode()
        ).hexdigest()
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="policy",
            payload={"intent": intent.model_dump(mode="json")},
            evidence=(
                EvidenceReference(
                    evidence_id=f"certified:{intent.semantic_contract.contract_id}:{intent.semantic_contract.contract_version}",
                    kind="decision",
                    fingerprint=fingerprint,
                ),
            ),
        )

    return handle


def _failure(node_input: NodeInput, reason: str) -> NodeOutput:
    fingerprint = hashlib.sha256(reason.encode()).hexdigest()
    return NodeOutput(
        run_id=node_input.run_id,
        node_id=node_input.node_id,
        status="failed",
        error=RunError(code="stale_context", message_reference=reason),
        evidence=(_evidence(f"certification-error:{node_input.run_id}", fingerprint),),
    )


def _evidence(identifier: str, fingerprint: str) -> EvidenceReference:
    return EvidenceReference(
        evidence_id=f"certification:{identifier}",
        kind="decision",
        fingerprint=fingerprint,
    )
