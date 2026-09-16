"""ADS-009 M0 composition and security harness through the durable boundary."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event

from app.runtime.control_store import ControlStore, ControlStoreError, StaleWorkerError
from packages.platform_contracts.agent_runtime import (
    AgentRunState,
    EvidenceReference,
    RunBudget,
    TerminalOutcome,
    Transition,
)
from packages.platform_contracts.routing import (
    RoutingConfig,
    RoutingContext,
    RoutingRefusal,
    TrustedAuthorizationArtifact,
    require_governed_action,
    resolve_route,
)
from packages.platform_contracts.tool_registry import RiskClass, ToolRegistry, ToolRegistryError, ToolSpec

SERVICE_ROOT = Path(__file__).parent.parent


def evidence(seq: int) -> EvidenceReference:
    return EvidenceReference(evidence_id=f"transition-{seq}", kind="transition", fingerprint=f"fp-{seq}")


def _db(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'ads009.db'}"
    monkeypatch.setenv("ANALYTICS_CONTROL_DB_URL", url)
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    command.upgrade(config, "head")
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    return engine


def _initial_state(now: datetime) -> AgentRunState:
    return AgentRunState(
        run_id="run-ads009", request_id="req-1", tenant_id="tenant-a", purpose="reporting",
        graph_version="fake-v1", current_node="create", context_snapshot_id="snapshot-1",
        budget=RunBudget(deadline=now + timedelta(minutes=5), max_transitions=32),
    )


def _next_state(state: AgentRunState, node: str, *, terminal: bool = False, now: datetime) -> AgentRunState:
    outcome = None
    status = "active"
    if terminal:
        status = "terminal"
        outcome = TerminalOutcome(
            kind="succeeded", summary_reference="summary-1", evidence=(evidence(state.transition_count + 1),),
            completed_at=now,
        )
    return state.model_copy(
        update={"current_node": node, "status": status, "transition_count": state.transition_count + 1,
                "terminal_outcome": outcome}
    )


def _transition(state: AgentRunState, target: str | None, *, terminal: bool = False) -> Transition:
    return Transition(
        run_id=state.run_id, tenant_id=state.tenant_id, graph_version=state.graph_version,
        sequence=state.transition_count + 1, from_node=state.current_node, to_node=target,
        from_status=state.status, to_status="terminal" if terminal else "active",
        idempotency_key=f"{state.run_id}:{state.transition_count + 1}",
        evidence=(evidence(state.transition_count + 1),),
    )


def test_worker_loss_reload_fencing_and_terminal_outcome_survive_reopen(tmp_path, monkeypatch):
    engine = _db(tmp_path, monkeypatch)
    store = ControlStore(engine, lease_seconds=30)
    now = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    state = _initial_state(now)
    store.create_run(state)
    worker_a = store.acquire_lease(
        run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose,
        owner_id="worker-a", lease_token="lease-a", now=now,
    )

    first = _next_state(state, "bootstrap", now=now)
    store.commit_transition(first, _transition(state, "bootstrap"), fencing_seq=worker_a.fencing_seq)
    checkpoint = store.load_latest_checkpoint(run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose)
    assert checkpoint.current_node == "bootstrap" and checkpoint.transition_count == 1

    worker_b = store.acquire_lease(
        run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose,
        owner_id="worker-b", lease_token="lease-b", now=now + timedelta(seconds=31),
    )
    with pytest.raises(StaleWorkerError, match="stale worker"):
        store.commit_transition(
            _next_state(checkpoint, "retrieve", now=now), _transition(checkpoint, "retrieve"),
            fencing_seq=worker_a.fencing_seq,
        )

    current = checkpoint
    for target in ("retrieve", "resolve", "plan", "validate", "compile", "policy"):
        next_state = _next_state(current, target, now=now)
        store.commit_transition(next_state, _transition(current, target), fencing_seq=worker_b.fencing_seq)
        current = next_state
    terminal = _next_state(current, current.current_node, terminal=True, now=now)
    store.commit_transition(terminal, _transition(current, None, terminal=True), fencing_seq=worker_b.fencing_seq)

    reopened = create_engine(f"sqlite:///{tmp_path / 'ads009.db'}")
    replay_store = ControlStore(reopened)
    replay = replay_store.replay_transitions(run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose)
    persisted = replay_store.load_latest_checkpoint(run_id=state.run_id, tenant_id=state.tenant_id, purpose=state.purpose)
    assert len(replay) == 8
    assert replay[-1]["to_status"] == "terminal"
    assert persisted.status == "terminal" and persisted.terminal_outcome is not None


def test_child_identity_routing_and_tool_scope_fail_closed(tmp_path, monkeypatch):
    engine = _db(tmp_path, monkeypatch)
    store = ControlStore(engine)
    now = datetime.now(timezone.utc)
    state = _initial_state(now)
    store.create_run(state)
    with pytest.raises(ControlStoreError, match="identity"):
        store.acquire_lease(
            run_id=state.run_id, tenant_id="tenant-b", purpose=state.purpose,
            owner_id="worker", lease_token="wrong-tenant", now=now,
        )

    context = RoutingContext(tenant_id="tenant-a", request_id="req-2", purpose="reporting")
    disabled = resolve_route(RoutingConfig(tenant_modes={"tenant-a": "disabled"}), context)
    assert disabled.execute_governed is False
    governed = context.model_copy(update={"governed_enabled": True, "rollout_id": "rollout-1"})
    with pytest.raises(RoutingRefusal):
        require_governed_action(resolve_route(RoutingConfig(tenant_modes={"tenant-a": "governed"}), governed))
    issued = datetime.now(timezone.utc)
    artifact = TrustedAuthorizationArtifact.issue(
        artifact_id="artifact-1", tenant_id="tenant-a", request_id="req-2", purpose="reporting",
        rollout_id="rollout-1", approval_reference="approval-1", audit_event_id="audit-1",
        signing_key="test-key", issued_at=issued, expires_at=issued + timedelta(minutes=5),
    )
    decision = resolve_route(
        RoutingConfig(tenant_modes={"tenant-a": "governed"}),
        governed.model_copy(update={"authorization_artifact": artifact}), authorization_key="test-key",
    )
    require_governed_action(decision)

    registry = ToolRegistry((ToolSpec(
        tool_id="read_context", version="v1", capability="context.read", risk_class=RiskClass.READ,
        timeout_ms=1000, idempotency_mode="required", idempotency_key_required=True,
        input_contract_version="v1", output_contract_version="v1", required_scope="tenant_and_purpose",
        allowed_purposes=("reporting",),
    ),))
    metadata = registry.lookup(
        "read_context", "v1", input_contract_version="v1", output_contract_version="v1",
        tenant_id="tenant-a", purpose="reporting",
    )
    assert not hasattr(metadata, "execute")
    with pytest.raises(ToolRegistryError):
        registry.lookup(
            "read_context", "v1", input_contract_version="v1", output_contract_version="v1",
            tenant_id="tenant-a", purpose="billing",
        )
    with pytest.raises(ToolRegistryError):
        ToolRegistry((ToolSpec(
            tool_id="raw", version="v1", capability="raw_sql", risk_class=RiskClass.READ, timeout_ms=1000,
            idempotency_mode="none", input_contract_version="v1", output_contract_version="v1", required_scope="tenant",
        ),))
