"""Identity- and request-scoped graph bootstrap node."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.security import AnalyticsIdentity


@dataclass(frozen=True)
class BootstrapRequest:
    request_id: str
    request_text: str
    identity: AnalyticsIdentity

    def __post_init__(self) -> None:
        if not self.request_id.strip() or len(self.request_id) > 255:
            raise ValueError("request_id must contain 1 to 255 characters")
        if not 3 <= len(self.request_text.strip()) <= 2_000:
            raise ValueError("request_text must contain 3 to 2000 characters")


def identity_bootstrap_node(request: BootstrapRequest):
    """Bind a graph handler to trusted, already-authenticated request context."""

    def handle(node_input: NodeInput) -> NodeOutput:
        identity = request.identity
        failure = None
        if node_input.request_id != request.request_id:
            failure = "request_identity_mismatch"
        elif identity.tenant_id != node_input.tenant_id:
            failure = "tenant_identity_mismatch"
        elif node_input.purpose not in identity.purposes:
            failure = "purpose_not_authorized"
        if failure:
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                error=RunError(code="policy_denied", message_reference=f"bootstrap:{failure}"),
                evidence=(_decision_evidence(f"denied:{failure}"),),
            )

        request_fingerprint = hashlib.sha256(request.request_text.encode()).hexdigest()
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="retrieve",
            payload={"request_text": request.request_text.strip()},
            evidence=(_decision_evidence(f"accepted:{request_fingerprint}"),),
        )

    return handle


def _decision_evidence(value: str) -> EvidenceReference:
    fingerprint = hashlib.sha256(value.encode()).hexdigest()
    return EvidenceReference(
        evidence_id=f"bootstrap:{fingerprint[:32]}", kind="decision", fingerprint=fingerprint,
    )
