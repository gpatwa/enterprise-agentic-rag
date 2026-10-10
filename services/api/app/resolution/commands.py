"""Generate non-executable support command proposals from verified resolutions."""

from __future__ import annotations

import hashlib
import json

from app.resolution.evidence import EvidencePacket
from app.resolution.models import GroundedResolutionOutcome
from app.resolution.verification import VerificationResult
from app.support.commands import (
    ApprovalRequirement,
    RiskLevel,
    SupportCommand,
    SupportCommandType,
    SupportTenantPrincipalContext,
)

_CONTRACT_VERSION = "support-command.v1"
_DRAFT_RESPONSE_ACTION = "draft_agent_response"


def generate_support_command(
    outcome: GroundedResolutionOutcome,
    verification: VerificationResult,
    evidence: EvidencePacket,
    context: SupportTenantPrincipalContext,
    *,
    contract_version: str = _CONTRACT_VERSION,
) -> SupportCommand | None:
    """Return a reviewable proposal, never an action or an execution request."""
    if not verification.verified or outcome.abstention:
        return None
    if outcome.next_action != _DRAFT_RESPONSE_ACTION:
        return None

    allowed = set(verification.allowed_labels)
    cited_labels = {
        label
        for claim in outcome.claims
        for label in claim.citation_labels
    } | {
        label
        for step in outcome.steps
        for label in step.citation_labels
    }
    cited_labels |= {citation.label for citation in outcome.citations}
    items = {item.label: item for item in evidence.items}
    if not cited_labels or not cited_labels.issubset(allowed) or not cited_labels.issubset(items):
        return None

    # Source IDs are the stable lineage identifiers validated by verification.
    evidence_ids = tuple(items[label].source_id for label in sorted(cited_labels))
    if not evidence_ids or len(set(evidence_ids)) != len(evidence_ids):
        return None

    parameters = {"response": outcome.customer_response}
    identity = {
        "action": outcome.next_action,
        "parameters": parameters,
        "evidence_ids": evidence_ids,
        "packet_version": evidence.packet_version,
        "contract_version": contract_version,
        "tenant_id": context.tenant_id,
        "principal_id": context.principal_id,
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return SupportCommand(
        command_type=SupportCommandType.SEND_CUSTOMER_REPLY,
        parameters=parameters,
        evidence_ids=evidence_ids,
        idempotency_key=f"resolution-command:{digest}",
        # The generator fixes the minimum safe contract; LLM output cannot lower it.
        risk_level=RiskLevel.LOW,
        approval_requirement=ApprovalRequirement.REQUIRED,
        contract_version=contract_version,
        context=context,
    )


propose_support_command = generate_support_command

__all__ = ["generate_support_command", "propose_support_command"]
