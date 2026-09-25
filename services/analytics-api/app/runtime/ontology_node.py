"""Certified-ontology resolution for model-proposed semantic IDs."""

from __future__ import annotations

import hashlib
import re

from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.analytics_planning import AnalyticsAmbiguity
from packages.platform_contracts.ontology import OntologySnapshot
from packages.platform_contracts.semantic import SemanticContract


class IntentResolutionError(ValueError):
    def __init__(self, code: str, candidates: tuple[str, ...] = (), ambiguity_code: str = "metric"):
        self.code = code
        self.candidates = candidates
        self.ambiguity_code = ambiguity_code
        super().__init__(code)


def resolve_certified_intent(
    intent: AnalyticalIntent, contract: SemanticContract, ontology: OntologySnapshot
) -> AnalyticalIntent:
    if ontology.tenant_id != contract.tenant_id or intent.tenant_id != contract.tenant_id:
        raise IntentResolutionError("tenant_scope_mismatch")
    allowed = {
        "metric": {item.id for item in contract.metrics if item.certification == "certified"},
        "dimension": {item.id for item in contract.dimensions},
        "field": {item.id for item in contract.fields},
        "dataset": {item.id for item in contract.datasets},
    }
    aliases: dict[str, dict[str, set[str]]] = {kind: {} for kind in allowed}
    for node in ontology.nodes:
        kind = "field" if node.node_type == "field" else node.node_type
        if node.lifecycle != "certified" or kind not in allowed or node.node_id not in allowed[kind]:
            continue
        for alias in (
            node.label,
            *_aliases(node.attributes.get("aliases")),
            *_aliases(node.attributes.get("synonyms")),
        ):
            key = _normalize(alias)
            if key:
                aliases[kind].setdefault(key, set()).add(node.node_id)

    def canonical(kind: str, identifier: str) -> str:
        if identifier in allowed[kind]:
            return identifier
        matches = aliases[kind].get(_normalize(identifier), set())
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            ambiguity_code = {
                "dimension": "time" if intent.time_range else "grain",
                "field": "filter",
            }.get(kind, kind)
            raise IntentResolutionError("ambiguous_semantic_alias", tuple(sorted(matches)), ambiguity_code)
        raise IntentResolutionError("unknown_or_uncertified_semantic_id")

    values = intent.model_dump(mode="python")
    values["dataset_id"] = canonical("dataset", intent.dataset_id)
    values["metrics"] = [
        {**metric.model_dump(), "metric_id": canonical("metric", metric.metric_id)} for metric in intent.metrics
    ]
    values["group_by"] = [
        {**group.model_dump(), "dimension_id": canonical("dimension", group.dimension_id)} for group in intent.group_by
    ]
    if intent.time_range:
        values["time_range"] = {
            **intent.time_range.model_dump(),
            "dimension_id": canonical("dimension", intent.time_range.dimension_id),
        }
    values["filters"] = [
        {**item.model_dump(), "field_id": canonical("field", item.field_id)} for item in intent.filters
    ]
    resolved = AnalyticalIntent.model_validate(values)
    resolved.validate_against(contract)
    certified_nodes = {node.node_id for node in ontology.nodes if node.lifecycle == "certified"}
    selected = {resolved.dataset_id, *(metric.metric_id for metric in resolved.metrics)}
    selected.update(group.dimension_id for group in resolved.group_by)
    selected.update(item.field_id for item in resolved.filters)
    if resolved.time_range:
        selected.add(resolved.time_range.dimension_id)
    if selected - certified_nodes:
        raise IntentResolutionError("selected_ids_not_ontology_certified")
    uncertified_metrics = {
        metric.metric_id
        for metric in resolved.metrics
        if next(item for item in contract.metrics if item.id == metric.metric_id).certification != "certified"
    }
    if uncertified_metrics:
        raise IntentResolutionError("selected_metrics_not_certified")
    return resolved


def ontology_resolution_node(contracts, ontologies):
    """Create a handler whose lookups are exact, tenant-scoped snapshot reads."""

    def handle(node_input: NodeInput) -> NodeOutput:
        try:
            proposed = AnalyticalIntent.model_validate(node_input.payload.get("intent"))
            contract = contracts.get_certified(
                proposed.semantic_contract.contract_id,
                proposed.semantic_contract.contract_version,
            ).contract
            ontology = ontologies.get(node_input.context_snapshot_id, node_input.tenant_id)
            if ontology.snapshot_id != node_input.context_snapshot_id:
                raise IntentResolutionError("ontology_snapshot_mismatch")
            resolved = resolve_certified_intent(proposed, contract, ontology)
            if resolved.tenant_id != node_input.tenant_id:
                raise IntentResolutionError("tenant_scope_mismatch")
        except IntentResolutionError as exc:
            if exc.candidates and exc.code == "ambiguous_semantic_alias":
                previous = node_input.payload.get("clarification_state") or {}
                try:
                    count = int(previous.get("continuation_count", 0))
                    if count >= 2:
                        raise ValueError("clarification limit reached")
                    state = {
                        "query_id": proposed.query_id,
                        "request_fingerprint": hashlib.sha256((node_input.request_text or "").encode()).hexdigest(),
                        "run_id": node_input.run_id,
                        "tenant_id": node_input.tenant_id,
                        "purpose": node_input.purpose,
                        "ambiguities": [
                            AnalyticsAmbiguity(
                                code=exc.ambiguity_code,
                                prompt=f"Select the intended certified {exc.ambiguity_code}.",
                                candidate_ids=list(exc.candidates),
                            ).model_dump(mode="json")
                        ],
                        "continuation_count": count,
                    }
                    return NodeOutput(
                        run_id=node_input.run_id,
                        node_id=node_input.node_id,
                        status="waiting",
                        next_node="clarify",
                        payload={
                            "clarification_state": state,
                            "approval_state": {"reason": "ambiguous_certified_reference"},
                        },
                        evidence=(_evidence(node_input, f"ambiguity:{exc.ambiguity_code}:{','.join(exc.candidates)}"),),
                    )
                except Exception as clarification_exc:  # noqa: BLE001 - ambiguous loops must stop.
                    exc = IntentResolutionError(f"clarification_rejected:{type(clarification_exc).__name__}")
            reason = exc.code
            fingerprint = hashlib.sha256(reason.encode()).hexdigest()
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                error=RunError(code="stale_context", message_reference=f"ontology:{reason}"),
                evidence=(
                    EvidenceReference(
                        evidence_id=f"ontology-error:{node_input.run_id}",
                        kind="error",
                        fingerprint=fingerprint,
                    ),
                ),
            )
        except Exception as exc:  # noqa: BLE001 - unresolved identifiers fail before planning.
            reason = exc.code if isinstance(exc, IntentResolutionError) else type(exc).__name__
            fingerprint = hashlib.sha256(reason.encode()).hexdigest()
            return NodeOutput(
                run_id=node_input.run_id,
                node_id=node_input.node_id,
                status="failed",
                error=RunError(code="stale_context", message_reference=f"ontology:{reason}"),
                evidence=(
                    EvidenceReference(
                        evidence_id=f"ontology-error:{node_input.run_id}",
                        kind="error",
                        fingerprint=fingerprint,
                    ),
                ),
            )
        fingerprint = hashlib.sha256(resolved.model_dump_json().encode()).hexdigest()
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="plan",
            payload={"intent": resolved.model_dump(mode="json")},
            evidence=(
                EvidenceReference(
                    evidence_id=f"ontology:{node_input.context_snapshot_id}:{resolved.dataset_id}",
                    kind="context",
                    fingerprint=fingerprint,
                ),
            ),
        )

    return handle


def _normalize(value: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", value.casefold()))


def _aliases(value) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(item for item in value if isinstance(item, str))
    return ()


def _evidence(node_input: NodeInput, value: str) -> EvidenceReference:
    fingerprint = hashlib.sha256(value.encode()).hexdigest()
    return EvidenceReference(
        evidence_id=f"ontology:{node_input.run_id}:{fingerprint[:24]}",
        kind="decision",
        fingerprint=fingerprint,
    )
