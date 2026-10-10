"""Identity-bound, two-turn clarification state transitions."""

from __future__ import annotations

import hashlib

from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.analytics_planning import AnalyticsAmbiguity, AnalyticsClarificationState
from packages.platform_contracts.security import AnalyticsIdentity


class ClarificationError(ValueError):
    pass


def start_clarification(
    *,
    query_id: str,
    run_id: str,
    tenant_id: str,
    purpose: str,
    request_fingerprint: str,
    ambiguities: list[AnalyticsAmbiguity],
) -> AnalyticsClarificationState:
    if not ambiguities or len(ambiguities) > 5:
        raise ClarificationError("clarification requires one to five targeted ambiguities")
    return AnalyticsClarificationState(
        query_id=query_id,
        run_id=run_id,
        tenant_id=tenant_id,
        purpose=purpose,
        request_fingerprint=request_fingerprint,
        ambiguities=ambiguities,
    )


def resume_clarification(
    state: AnalyticsClarificationState,
    *,
    identity: AnalyticsIdentity,
    run_id: str,
    query_id: str,
    purpose: str,
    ambiguity_code: str,
    selected_id: str,
) -> AnalyticsClarificationState:
    if state.run_id != run_id or state.query_id != query_id or state.tenant_id != identity.tenant_id:
        raise ClarificationError("clarification identity does not match the original run")
    if state.purpose != purpose or purpose not in identity.purposes:
        raise ClarificationError("clarification purpose is not authorized for this identity")
    if state.continuation_count >= 2:
        raise ClarificationError("clarification continuation limit reached")
    ambiguity = next((item for item in state.ambiguities if item.code == ambiguity_code), None)
    if ambiguity is None or selected_id not in ambiguity.candidate_ids:
        raise ClarificationError("selected option is not a candidate for this clarification")
    choices = {**state.selected_choices, ambiguity_code: selected_id}
    return state.model_copy(update={"selected_choices": choices, "continuation_count": state.continuation_count + 1})


def clarification_node():
    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            state = AnalyticsClarificationState.model_validate(node_input.payload.get("clarification_state"))
            intent = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            if (
                state.run_id != node_input.run_id
                or state.tenant_id != node_input.tenant_id
                or state.purpose != node_input.purpose
                or state.query_id != node_input.request_id
                or state.request_fingerprint != hashlib.sha256((node_input.request_text or "").encode()).hexdigest()
            ):
                raise ClarificationError("clarification state does not match the active run")
            if not state.selected_choices:
                raise ClarificationError("a candidate selection is required to resume clarification")
            values = intent.model_dump(mode="python")
            for ambiguity in state.ambiguities:
                selected = state.selected_choices.get(ambiguity.code)
                if selected is None:
                    continue
                if selected not in ambiguity.candidate_ids:
                    raise ClarificationError("selected candidate is no longer eligible")
                if ambiguity.code == "metric":
                    values["metrics"][0]["metric_id"] = selected
                elif ambiguity.code == "dataset":
                    values["dataset_id"] = selected
                elif ambiguity.code in {"time", "grain"}:
                    if values["time_range"]:
                        values["time_range"]["dimension_id"] = selected
                    elif values["group_by"]:
                        values["group_by"][0]["dimension_id"] = selected
                    else:
                        values["group_by"] = [{"dimension_id": selected}]
                elif ambiguity.code == "filter" and values["filters"]:
                    values["filters"][0]["field_id"] = selected
            intent = AnalyticalIntent.model_validate(values)
        except Exception as exc:  # noqa: BLE001 - invalid clarification cannot advance the graph.
            reason = type(exc).__name__
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                error=RunError(code="stale_context", message_reference=f"clarification:{reason}"),
                evidence=(_evidence(f"clarification-failed:{node_input.run_id}:{reason}"),),
            )
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="resolve",
            payload={"intent": intent.model_dump(mode="json"), "clarification_state": state.model_dump(mode="json")},
            evidence=(_evidence(f"clarification-resumed:{node_input.run_id}:{state.continuation_count}"),),
        )

    return handle


def _evidence(value: str) -> EvidenceReference:
    fingerprint = hashlib.sha256(value.encode()).hexdigest()
    return EvidenceReference(evidence_id=f"clarification:{fingerprint[:32]}", kind="decision", fingerprint=fingerprint)
