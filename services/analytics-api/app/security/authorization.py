"""Fail-closed contract policy evaluation."""

from __future__ import annotations

from uuid import uuid4

from packages.platform_contracts.security import AnalyticsIdentity, AuthorizationDecision
from packages.platform_contracts.semantic import SemanticContract


def authorize(
    identity: AnalyticsIdentity, contract: SemanticContract, target_ids: set[str], purpose: str
) -> AuthorizationDecision:
    if identity.tenant_id != contract.tenant_id:
        return AuthorizationDecision(
            decision_id=uuid4().hex, effect="deny", reasons=["tenant_mismatch"], policy_version=contract.version
        )
    applicable = [policy for policy in contract.policies if target_ids.intersection(policy.target_ids)]
    required_filters = sorted({filter_id for policy in applicable for filter_id in policy.required_filter_ids})
    denied = [policy.id for policy in applicable if purpose not in policy.allowed_purposes]
    if denied:
        return AuthorizationDecision(
            decision_id=uuid4().hex,
            effect="deny",
            reasons=[f"purpose_not_allowed:{policy_id}" for policy_id in denied],
            enforced_filter_ids=required_filters,
            policy_version=contract.version,
        )
    needs_review = [
        policy.id
        for policy in applicable
        if policy.classification in {"confidential", "restricted"} and not identity.groups
    ]
    if needs_review:
        return AuthorizationDecision(
            decision_id=uuid4().hex,
            effect="review",
            reasons=[f"group_required:{policy_id}" for policy_id in needs_review],
            enforced_filter_ids=required_filters,
            policy_version=contract.version,
        )
    reasons = [f"policy_allowed:{policy.id}" for policy in applicable] or ["no_restrictive_policy"]
    return AuthorizationDecision(
        decision_id=uuid4().hex,
        effect="allow",
        reasons=reasons,
        enforced_filter_ids=required_filters,
        policy_version=contract.version,
    )
