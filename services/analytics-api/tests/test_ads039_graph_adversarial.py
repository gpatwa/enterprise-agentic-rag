"""ADS-039 adversarial corpus against the composed local graph-v2 runtime."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from app.compiler.service import CertifiedIntentCompiler
from app.runtime import (
    AgentGraphRunner,
    BootstrapRequest,
    CompiledPlanStore,
    ControlStore,
    GraphEvaluationCase,
    analytics_plan_node,
    certified_intent_node,
    compile_node,
    context_retrieval_node,
    estimate_node,
    evaluate_graph_cases,
    fake_execution_node,
    governed_graph_v2,
    identity_bootstrap_node,
    ontology_resolution_node,
    policy_node,
    review_decision_node,
    structured_intent_node,
    validate_m3_coverage,
)
from app.runtime.clarification import clarification_node
from app.runtime.governed_stages import PolicyValueStore
from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.agent_runtime import (
    AgentRunState,
    CancellationRequest,
    NodeInput,
    NodeOutput,
    RunBudget,
    Transition,
)
from packages.platform_contracts.context_snapshot import ContextPackItem, ContextSnapshot
from packages.platform_contracts.metadata import MetadataAsset, MetadataColumn
from packages.platform_contracts.ontology import OntologyNode, OntologyProvenance, OntologySnapshot
from packages.platform_contracts.security import AnalyticsIdentity
from packages.platform_contracts.semantic import SemanticPolicy, SemanticRegistryDocument

SERVICE_ROOT = Path(__file__).parent.parent
TENANT = "tenant-a"
PURPOSE = "analytics"
SNAPSHOT_ID = "ads039-context-v1"
NOW = datetime.now(timezone.utc)


class RecordingControlStore(ControlStore):
    def __init__(self, engine):
        super().__init__(engine)
        self.transitions: dict[str, list[Transition]] = {}
        self.last_lease = None

    def acquire_lease(self, **kwargs):
        self.last_lease = super().acquire_lease(**kwargs)
        return self.last_lease

    def commit_transition(self, state, transition, *, fencing_seq):
        super().commit_transition(state, transition, fencing_seq=fencing_seq)
        self.transitions.setdefault(state.run_id, []).append(transition)


class SnapshotProvider:
    def __init__(self, snapshot: ContextSnapshot, *, stale: bool = False):
        self.snapshot = snapshot
        self.stale = stale

    def get(self, snapshot_id: str, tenant_id: str) -> ContextSnapshot:
        if self.stale:
            return self.snapshot.model_copy(update={"tenant_id": "other-tenant"})
        assert snapshot_id == self.snapshot.snapshot_id
        assert tenant_id == self.snapshot.tenant_id
        return self.snapshot


class SearchProvider:
    def search(self, query: str, *, tenant_id: str, snapshot_id: str, certified_only=True, limit=10):
        assert tenant_id == TENANT
        assert snapshot_id == SNAPSHOT_ID
        assert certified_only is True
        assert 1 <= limit <= 20
        return (
            ContextPackItem(
                asset_id="orders",
                score=1.0,
                text="Certified sales orders dataset with revenue and order dates.",
                citation=f"context:{snapshot_id}:orders",
                certified=True,
            ),
        )


class ContractsProvider:
    def __init__(self, document: SemanticRegistryDocument):
        self.document = document

    def get_certified(self, contract_id: str, version: str):
        if (contract_id, version) != (self.document.contract.id, self.document.contract.version):
            raise LookupError("exact certified contract not found")
        if self.document.lifecycle != "certified":
            raise LookupError("contract is not certified")
        return self.document


class OntologyProvider:
    def __init__(self, snapshot: OntologySnapshot):
        self.snapshot = snapshot

    def get(self, snapshot_id: str, tenant_id: str):
        if (snapshot_id, tenant_id) != (self.snapshot.snapshot_id, self.snapshot.tenant_id):
            raise LookupError("ontology snapshot scope mismatch")
        return self.snapshot


class IntentClient:
    def __init__(self, value):
        self.value = value

    def complete_json(self, *, prompt: str, schema: dict, max_tokens: int):
        assert "Never emit SQL" in prompt
        assert max_tokens == 1_024
        assert schema["additionalProperties"] is False
        return self.value


class Estimator:
    def __init__(self, cost: float):
        self.cost = cost

    def estimate(self, compiled_plan):
        assert compiled_plan.sql.startswith("SELECT")
        return self.cost


class FakeExecutor:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    def execute(self, *, tenant_id: str, run_id: str, plan_reference: str):
        self.calls.append((tenant_id, run_id, plan_reference))
        return f"result:{run_id}"


def _database(tmp_path: Path, monkeypatch) -> RecordingControlStore:
    database_url = f"sqlite:///{tmp_path / 'ads039.db'}"
    monkeypatch.setenv("ANALYTICS_CONTROL_DB_URL", database_url)
    config = Config(str(SERVICE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVICE_ROOT / "alembic"))
    command.upgrade(config, "head")
    return RecordingControlStore(create_engine(database_url))


def _registry_document(*, denied: bool = False) -> SemanticRegistryDocument:
    base = SemanticRegistry(SERVICE_ROOT / "semantic_registry").get_certified("sales-core", "v1")
    if not denied:
        return base
    policy = SemanticPolicy(
        id="deny-analytics",
        target_ids=["revenue"],
        classification="internal",
        allowed_purposes=["billing"],
        owner_ids=["team.data"],
    )
    contract = base.contract.model_copy(update={"policies": [policy]})
    return SemanticRegistryDocument(lifecycle="certified", contract=contract)


def _context(document: SemanticRegistryDocument, *, ambiguous: bool = False):
    contract = document.contract
    provenance = OntologyProvenance(
        source_system="ads039-fixture",
        source_id="sales-core-v1",
        source_version="v1",
        observed_at=NOW,
        fingerprint="a" * 64,
    )
    nodes = []
    for asset in (*contract.datasets, *contract.metrics, *contract.dimensions, *contract.fields):
        node_type = (
            "dataset"
            if asset in contract.datasets
            else "metric"
            if asset in contract.metrics
            else "dimension"
            if asset in contract.dimensions
            else "field"
        )
        label = "time" if ambiguous and node_type == "dimension" else asset.id
        nodes.append(
            OntologyNode(
                node_id=asset.id,
                tenant_id=contract.tenant_id,
                node_type=node_type,
                label=label,
                lifecycle="certified",
                valid_from=NOW - timedelta(days=1),
                provenance=(provenance.model_copy(update={"source_id": asset.id}),),
            )
        )
    ontology = OntologySnapshot(
        snapshot_id=SNAPSHOT_ID,
        tenant_id=contract.tenant_id,
        captured_at=NOW,
        nodes=tuple(nodes),
    )
    datasets = tuple(
        MetadataAsset(
            id=dataset.id,
            display_name=dataset.display_name,
            physical_name=dataset.physical_name,
            provider="semantic-registry",
            description=dataset.description,
            owner_ids=dataset.owner_ids,
            certified=True,
            source_version=f"{contract.id}@{contract.version}",
            observed_at=NOW,
            columns=[
                MetadataColumn(
                    name=field.physical_name,
                    data_type=field.data_type,
                    classification=field.classification,
                )
                for field in contract.fields
                if field.dataset_id == dataset.id
            ],
        )
        for dataset in contract.datasets
    )
    context = ContextSnapshot.build(
        snapshot_id=SNAPSHOT_ID,
        tenant_id=contract.tenant_id,
        source_fingerprints=("b" * 64,),
        metadata_assets=datasets,
        ontology=ontology,
        semantic_contract_ids=(f"{contract.id}@{contract.version}",),
        created_at=NOW,
    )
    return context, ontology


def _intent(case_id: str, *, ambiguous: bool = False) -> dict:
    value = json.loads((SERVICE_ROOT / "tests/fixtures/semantic/sales-monthly-intent.json").read_text())
    value.update({"query_id": case_id, "tenant_id": TENANT})
    if ambiguous:
        value["group_by"][0]["dimension_id"] = "time"
        value["time_range"]["dimension_id"] = "time"
    return value


def _state(case_id: str) -> AgentRunState:
    return AgentRunState(
        run_id=f"ads039-{case_id}",
        request_id=case_id,
        tenant_id=TENANT,
        purpose=PURPOSE,
        request_text=f"Show monthly revenue for {case_id}",
        graph_version="graph-v2",
        context_snapshot_id=SNAPSHOT_ID,
        budget=RunBudget(
            deadline=NOW - timedelta(seconds=1) if case_id == "deadline" else NOW + timedelta(minutes=5),
            max_transitions=40,
            max_cost_units=10 if case_id == "cost_budget" else 100,
            max_context_tokens=2_000,
            max_retrieval_candidates=10,
        ),
        cancellation=(
            CancellationRequest(
                requested_by="requester",
                reason="ADS-039 cancellation scenario",
                requested_at=NOW,
                policy_source="test-harness",
            )
            if case_id == "cancel"
            else None
        ),
        current_node="clarify" if case_id == "cycle" else "create",
    )


def _output(node_input: NodeInput, next_node: str) -> NodeOutput:
    return NodeOutput(
        run_id=node_input.run_id,
        node_id=node_input.node_id,
        status="completed",
        next_node=next_node,
    )


def _build_runner(case_id: str, store: RecordingControlStore, executor: FakeExecutor):
    denied = case_id == "refuse_policy"
    document = _registry_document(denied=denied)
    context, ontology = _context(document, ambiguous=case_id == "clarify")
    plans = CompiledPlanStore()
    policy_values = PolicyValueStore()
    identity = AnalyticsIdentity(
        tenant_id=TENANT,
        user_id="requester",
        purposes=["billing"] if case_id == "refuse_identity" else [PURPOSE],
        groups=["analyst"],
    )
    request = BootstrapRequest(
        request_id=case_id,
        request_text=f"Show monthly revenue for {case_id}",
        identity=identity,
    )
    intent_value = _intent(case_id, ambiguous=case_id == "clarify")
    if case_id == "malformed_intent":
        intent_value = {"raw_sql": "DROP TABLE orders"}
    snapshot_provider = SnapshotProvider(context, stale=case_id == "stale_context")
    contracts = ContractsProvider(document)
    handlers = {
        "create": lambda ni: _output(ni, "bootstrap"),
        "bootstrap": identity_bootstrap_node(request),
        "retrieve": context_retrieval_node(snapshot_provider, SearchProvider()),
        "extract_intent": structured_intent_node(IntentClient(intent_value)),
        "resolve": ontology_resolution_node(contracts, OntologyProvider(ontology)),
        "clarify": lambda ni: _output(ni, "clarify") if case_id == "cycle" else clarification_node()(ni),
        "plan": analytics_plan_node(contracts),
        "validate": certified_intent_node(contracts),
        "policy": policy_node(contracts, identity, policy_values, review_store=store),
        "compile": compile_node(CertifiedIntentCompiler(SERVICE_ROOT / "semantic_registry"), plans, policy_values),
        "estimate": estimate_node(
            plans,
            Estimator(
                25
                if case_id in {"review_pending", "review_approved", "review_rejected", "review_expired"}
                else 20
                if case_id == "cost_budget"
                else 1
            ),
            approval_threshold=10,
            review_store=store,
            requested_by=identity.user_id,
        ),
        "approve": review_decision_node(store),
        "execute": fake_execution_node(executor),
        "result_validate": lambda ni: _output(ni, "explain"),
        "explain": lambda ni: _output(ni, "terminal"),
    }
    if case_id == "crash_resume":
        failed_once = {"value": False}

        def crash_once(ni: NodeInput):
            if not failed_once["value"]:
                failed_once["value"] = True
                raise SystemExit("simulated worker crash after persisted checkpoint")
            return _output(ni, "terminal")

        handlers["explain"] = crash_once
    if case_id == "cycle":
        handlers["clarify"] = lambda ni: _output(ni, "clarify")
    return AgentGraphRunner(store, governed_graph_v2(handlers), now=lambda: NOW)


def _execute_case(case_id: str, state: AgentRunState, store: RecordingControlStore, executor: FakeExecutor):
    runner = _build_runner(case_id, store, executor)
    owner = f"worker-{case_id}"
    if case_id == "crash_resume":
        try:
            runner.start(state, owner_id=owner, lease_token=f"lease-{case_id}")
        except SystemExit as exc:
            assert "simulated worker crash" in str(exc)
        else:
            raise AssertionError("crash scenario did not interrupt the worker")
        run_id = state.run_id
        assert store.load_latest_checkpoint(run_id=run_id, tenant_id=TENANT, purpose=PURPOSE).current_node == "explain"
        store.release_lease(store.last_lease)
        resumed = runner.resume(
            run_id=run_id,
            tenant_id=TENANT,
            purpose=PURPOSE,
            owner_id=owner,
            lease_token="resume-crash-resume",
        )
        return replace(resumed, transitions=tuple(store.transitions[run_id]))

    first = runner.start(state, owner_id=owner, lease_token=f"lease-{case_id}")
    if case_id == "review_pending":
        return first
    if case_id in {"review_approved", "review_rejected", "review_expired"}:
        approval = first.state.approval_state or {}
        assert "review_id" in approval, (first.state.status, first.state.errors, first.state.cost_decision)
        review_id = approval["review_id"]
        review = store.get_review(review_id, tenant_id=TENANT, purpose=PURPOSE)
        if case_id == "review_expired":
            with store.engine.begin() as connection:
                connection.execute(
                    text("UPDATE analytics_run_reviews SET expires_at=:expires_at WHERE review_id=:review_id"),
                    {
                        "expires_at": (review.created_at + timedelta(microseconds=1)).isoformat(),
                        "review_id": review_id,
                    },
                )
        else:
            store.resolve_review(
                review_id,
                tenant_id=TENANT,
                purpose=PURPOSE,
                identity=AnalyticsIdentity(tenant_id=TENANT, user_id="reviewer", purposes=[PURPOSE]),
                decision="approved" if case_id == "review_approved" else "rejected",
                plan_fingerprint=review.plan_fingerprint,
                now=NOW,
            )
        result = runner.resume(
            run_id=state.run_id,
            tenant_id=TENANT,
            purpose=PURPOSE,
            owner_id=owner,
            lease_token=f"resume-{case_id}",
        )
        return replace(result, transitions=tuple(store.transitions[state.run_id]))
    return first


def test_ads039_executes_all_required_scenarios_against_graph_v2(tmp_path, monkeypatch):
    store = _database(tmp_path, monkeypatch)
    executor = FakeExecutor()
    case_ids = (
        "answer",
        "clarify",
        "refuse_identity",
        "refuse_policy",
        "review_pending",
        "review_approved",
        "review_rejected",
        "review_expired",
        "malformed_intent",
        "stale_context",
        "cost_budget",
        "deadline",
        "cycle",
        "cancel",
        "crash_resume",
    )
    cases = tuple(
        GraphEvaluationCase(
            case_id=case_id,
            build_state=lambda case_id=case_id: _state(case_id),
            expected_outcome={
                "answer": "succeeded",
                "clarify": None,
                "refuse_identity": "refused",
                "refuse_policy": "refused",
                "review_pending": None,
                "review_approved": "succeeded",
                "review_rejected": "refused",
                "review_expired": "review_required",
                "malformed_intent": "failed",
                "stale_context": "review_required",
                "cost_budget": "failed",
                "deadline": "failed",
                "cycle": "failed",
                "cancel": "cancelled",
                "crash_resume": "succeeded",
            }[case_id],
            run=lambda runner, state, case_id=case_id: _execute_case(case_id, state, store, executor),
        )
        for case_id in case_ids
    )
    baseline_runner = _build_runner("answer", store, executor)
    report = evaluate_graph_cases(baseline_runner, cases)
    findings = validate_m3_coverage(report)

    assert report.passed, report.cases
    assert findings == (), findings
    assert {case.case_id for case in report.cases} == set(case_ids)
    assert not {
        "clarify",
        "refuse_identity",
        "refuse_policy",
        "review_rejected",
        "review_expired",
        "malformed_intent",
        "stale_context",
        "cost_budget",
        "deadline",
        "cycle",
        "cancel",
    } & {run_id.removeprefix("ads039-") for _, run_id, _ in executor.calls}
