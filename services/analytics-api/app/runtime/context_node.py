"""Tenant-scoped context retrieval and bounded one-hop expansion node."""

from __future__ import annotations

import hashlib
from typing import Protocol

from packages.platform_contracts.agent_runtime import EvidenceReference, NodeInput, NodeOutput, RunError
from packages.platform_contracts.context_snapshot import ContextSnapshot, build_context_pack


class ContextSnapshotProvider(Protocol):
    def get(self, snapshot_id: str, tenant_id: str) -> ContextSnapshot: ...


class ContextSearchProvider(Protocol):
    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        snapshot_id: str,
        certified_only: bool = True,
        limit: int = 10,
    ): ...


def context_retrieval_node(
    snapshots: ContextSnapshotProvider,
    search: ContextSearchProvider,
    *,
    token_budget: int = 4_000,
    candidate_limit: int = 20,
    max_graph_edges: int = 24,
):
    if not 1 <= candidate_limit <= 100 or not 1 <= token_budget <= 32_000:
        raise ValueError("context retrieval limits are outside the supported bounds")

    def handle(node_input: NodeInput) -> NodeOutput:
        if not node_input.request_text:
            return _failure(node_input, "missing_request")
        try:
            snapshot = snapshots.get(node_input.context_snapshot_id, node_input.tenant_id)
            if snapshot.snapshot_id != node_input.context_snapshot_id or snapshot.tenant_id != node_input.tenant_id:
                return _failure(node_input, "context_scope_mismatch")
            results = search.search(
                node_input.request_text,
                tenant_id=node_input.tenant_id,
                snapshot_id=node_input.context_snapshot_id,
                certified_only=True,
                limit=min(candidate_limit, node_input.remaining_budget.max_retrieval_candidates),
            )
            if any(not item.citation.startswith(f"context:{snapshot.snapshot_id}") for item in results):
                return _failure(node_input, "retrieval_snapshot_mismatch")
            pack = build_context_pack(
                snapshot,
                tuple(results),
                query=node_input.request_text,
                token_budget=min(token_budget, node_input.remaining_budget.max_context_tokens),
                graph_depth=1,
                max_graph_edges=max_graph_edges,
            )
        except Exception as exc:  # noqa: BLE001 - provider failures fail closed before model use.
            return _failure(node_input, f"context_provider:{type(exc).__name__}")
        evidence = tuple(
            EvidenceReference(
                evidence_id=f"context:{pack.snapshot_id}:{item.asset_id}",
                kind="context",
                fingerprint=hashlib.sha256(item.citation.encode()).hexdigest(),
            )
            for item in pack.items
        )
        relation_evidence = tuple(
            EvidenceReference(
                evidence_id=f"context:{pack.snapshot_id}:{edge.edge_id}",
                kind="context",
                fingerprint=hashlib.sha256(edge.citation.encode()).hexdigest(),
            )
            for edge in pack.graph_closure
        )
        return NodeOutput(
            run_id=node_input.run_id,
            node_id=node_input.node_id,
            status="completed",
            next_node="extract_intent",
            payload={"context_pack": pack.model_dump(mode="json")},
            evidence=evidence + relation_evidence or (_fingerprint_evidence(pack.snapshot_id, "empty-context"),),
        )

    return handle


def _failure(node_input: NodeInput, reference: str) -> NodeOutput:
    return NodeOutput(
        run_id=node_input.run_id,
        node_id=node_input.node_id,
        status="failed",
        error=RunError(code="stale_context", message_reference=reference),
        evidence=(_fingerprint_evidence(node_input.context_snapshot_id, reference),),
    )


def _fingerprint_evidence(snapshot_id: str, value: str) -> EvidenceReference:
    fingerprint = hashlib.sha256(value.encode()).hexdigest()
    return EvidenceReference(
        evidence_id=f"context:{snapshot_id}:{fingerprint[:24]}", kind="context", fingerprint=fingerprint
    )
