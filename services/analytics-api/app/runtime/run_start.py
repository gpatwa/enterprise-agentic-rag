"""Select and pin the context snapshot a governed run executes against."""

from __future__ import annotations

from typing import Protocol

from app.context.refresh import StaleSnapshotError
from app.runtime.bootstrap import BootstrapRequest
from packages.platform_contracts.agent_runtime import AgentRunState, RunBudget
from packages.platform_contracts.context_snapshot import ContextSnapshot


class SnapshotSelectionError(ValueError):
    """The run cannot start; `code` is stable and carries no snapshot content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class SnapshotSource(Protocol):
    """Satisfied by `ContextRefreshWorker`: the tenant's latest verified snapshot, or an error."""

    def current_snapshot(self) -> ContextSnapshot: ...


def select_context_snapshot(
    source: SnapshotSource, *, tenant_id: str, require_ontology: bool = True
) -> ContextSnapshot:
    """Return the snapshot a new run may use, failing closed before any run exists."""
    try:
        snapshot = source.current_snapshot()
    except StaleSnapshotError as exc:
        raise SnapshotSelectionError("snapshot_stale") from exc
    except LookupError as exc:  # includes NoSnapshotError and a missing registry entry
        raise SnapshotSelectionError("snapshot_unavailable") from exc
    if snapshot.tenant_id != tenant_id:
        raise SnapshotSelectionError("snapshot_tenant_mismatch")
    if require_ontology and snapshot.ontology is None:
        raise SnapshotSelectionError("snapshot_has_no_ontology")
    return snapshot


def new_governed_run_state(
    source: SnapshotSource,
    request: BootstrapRequest,
    *,
    run_id: str,
    purpose: str,
    budget: RunBudget,
    graph_version: str = "graph-v2",
    require_ontology: bool = True,
) -> AgentRunState:
    """Build the initial run state with the selected snapshot pinned for the whole run.

    The pinned ID is persisted in the state, so resumes and replays keep using the same
    snapshot even after newer ones are published. Identity is checked here only to scope
    the selection (tenant, purpose); the bootstrap node remains the authoritative gate.
    """
    identity = request.identity
    if purpose not in identity.purposes:
        raise SnapshotSelectionError("purpose_not_authorized")
    snapshot = select_context_snapshot(source, tenant_id=identity.tenant_id, require_ontology=require_ontology)
    return AgentRunState(
        run_id=run_id,
        request_id=request.request_id,
        tenant_id=identity.tenant_id,
        purpose=purpose,
        request_text=request.request_text.strip(),
        graph_version=graph_version,
        current_node="create",
        context_snapshot_id=snapshot.snapshot_id,
        budget=budget,
    )
