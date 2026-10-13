"""Dispatch agent tool calls to the governed analytics service (ADS-060).

The surface adds no authority of its own. Identity, purpose scope, idempotency, requester binding, and review
separation of duties are all enforced by `GovernedAnalyzeService` exactly as for REST. The only things added here are
strict argument validation, a human-only rule for the review tool, and a data-free evidence summary.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.agent_tools.audit import ToolAudit
from app.runtime.analyze_service import GovernedAnalyzeService, ServiceError
from app.runtime.evidence_store import EvidenceNotFoundError, EvidenceStore
from app.security.identity import caller_kind
from packages.platform_contracts.agent_tools import (
    ARGUMENT_MODELS,
    TOOLS,
    EvidenceSummary,
    ToolCall,
    ToolError,
    ToolResult,
    catalog,
)
from packages.platform_contracts.evidence import EvidenceEnvelope
from packages.platform_contracts.security import AnalyticsIdentity


class AgentToolSurface:
    def __init__(
        self,
        service: GovernedAnalyzeService,
        evidence: EvidenceStore | None = None,
        audit: ToolAudit | None = None,
    ) -> None:
        self.service = service
        self.evidence = evidence
        self.audit = audit
        self._specs = {spec.name: spec for spec in TOOLS}

    def catalog(self) -> list[dict[str, Any]]:
        return catalog()

    def call(
        self, identity: AnalyticsIdentity, call: ToolCall | dict[str, Any], *, transport: str = "direct"
    ) -> ToolResult:
        """Run one tool call and, when an audit is configured, append one audit event for it (refusals included)."""
        result = self._call(identity, call)
        if self.audit is not None:
            arguments = (
                call.arguments
                if isinstance(call, ToolCall)
                else (call or {}).get("arguments")
                if isinstance(call, dict)
                else None
            )
            self.audit.record_call(identity, tool=result.tool, transport=transport, result=result, arguments=arguments)
        return result

    def _call(self, identity: AnalyticsIdentity, call: ToolCall | dict[str, Any]) -> ToolResult:
        try:
            request = call if isinstance(call, ToolCall) else ToolCall.model_validate(call)
        except ValidationError:
            return _error("invalid", "invalid_tool_call", 422)
        spec = self._specs.get(request.tool)
        if spec is None:
            return _error(request.tool[:64], "unknown_tool", 404)
        try:
            args = ARGUMENT_MODELS[spec.name].model_validate(request.arguments)
        except ValidationError:
            return _error(spec.name, "invalid_arguments", 422)  # never echoes the offending value
        if spec.human_only and caller_kind(identity) != "human":
            return _error(spec.name, "human_required", 403)
        try:
            return self._dispatch(identity, spec.name, args)
        except ServiceError as exc:
            return _error(spec.name, exc.code, exc.status)
        except Exception:  # noqa: BLE001 - a tool call never leaks an exception's text.
            return _error(spec.name, "internal_error", 500)

    def _dispatch(self, identity: AnalyticsIdentity, tool: str, args: Any) -> ToolResult:
        service = self.service
        if tool == "analytics.analyze":
            run = service.analyze(
                identity, purpose=args.purpose, idempotency_key=args.idempotency_key, request_text=args.request_text
            )
        elif tool == "analytics.status":
            run = service.status(identity, purpose=args.purpose, run_id=args.run_id)
        elif tool == "analytics.clarify":
            run = service.clarify(
                identity,
                purpose=args.purpose,
                run_id=args.run_id,
                ambiguity_code=args.ambiguity_code,
                selected_id=args.selected_id,
            )
        elif tool == "analytics.review":
            run = service.decide_review(
                identity,
                purpose=args.purpose,
                run_id=args.run_id,
                decision=args.decision,
                plan_fingerprint=args.plan_fingerprint,
                note=args.note,
            )
        else:
            return self._evidence(identity, args.purpose, args.run_id)
        return ToolResult(tool=tool, ok=True, run=run)

    def _evidence(self, identity: AnalyticsIdentity, purpose: str, run_id: str) -> ToolResult:
        if self.evidence is None:
            return _error("analytics.evidence", "evidence_not_configured", 503)
        # status() authorizes the purpose and proves the run is visible to this tenant and purpose.
        run = self.service.status(identity, purpose=purpose, run_id=run_id)
        if run.state != "terminal":
            return _error("analytics.evidence", "run_not_terminal", 409)
        try:
            envelope = self.evidence.get(run_id, tenant_id=identity.tenant_id, purpose=purpose)
            seq, chain_hash = self.evidence.seal_position(run_id, tenant_id=identity.tenant_id, purpose=purpose)
        except EvidenceNotFoundError:
            return _error("analytics.evidence", "evidence_unavailable", 409)
        return ToolResult(tool="analytics.evidence", ok=True, evidence=summarize_evidence(envelope, seq, chain_hash))


def summarize_evidence(envelope: EvidenceEnvelope, chain_seq: int, chain_hash: str) -> EvidenceSummary:
    result, policy, cost = envelope.result, envelope.policy, envelope.cost
    return EvidenceSummary(
        envelope_id=envelope.envelope_id,
        content_fingerprint=envelope.content_fingerprint,
        chain_seq=chain_seq,
        chain_hash=chain_hash,
        run_id=envelope.run_id,
        terminal_kind=envelope.terminal_kind,
        context_snapshot_id=envelope.context_snapshot_id,
        semantic_contract=envelope.semantic_contract,
        intent_fingerprint=envelope.intent_fingerprint,
        policy_effect=policy.effect if policy else None,
        policy_version=policy.policy_version if policy else None,
        policy_reasons=tuple(policy.reasons) if policy else (),
        estimated_cost_units=cost.estimated_cost_units if cost else None,
        observed_cost_units=cost.observed_cost_units if cost else None,
        approval_state=envelope.approval.state if envelope.approval else None,
        validation_status=result.validation_status if result else None,
        validation_fingerprint=result.validation_fingerprint if result else None,
        result_fingerprint=result.result_fingerprint if result else None,
        plan_fingerprint=result.plan_fingerprint if result else None,
        row_count=result.row_count if result else None,
        issue_codes=tuple(result.issue_codes) if result else (),
        error_codes=tuple(error.code for error in envelope.errors),
        clarification_codes=tuple(envelope.clarification.ambiguity_codes) if envelope.clarification else (),
        transition_count=len(envelope.transitions),
        completed_at=envelope.completed_at,
    )


def _error(tool: str, code: str, status: int) -> ToolResult:
    return ToolResult(tool=tool, ok=False, error=ToolError(code=code, status=status))
