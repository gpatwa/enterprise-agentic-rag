"""ADS-042: every terminal outcome is sealed with required provenance, append-only and chained."""

from __future__ import annotations

from datetime import datetime, timezone

import duckdb
import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_ads039_graph_adversarial import (
    NOW,
    PURPOSE,
    SERVICE_ROOT,
    TENANT,
    ContractsProvider,
    FakeExecutor,
    IntentClient,
    OntologyProvider,
    SearchProvider,
    SnapshotProvider,
    _context,
    _database,
    _execute_case,
    _intent,
    _registry_document,
    _state,
)

from app.compiler import DuckDBCompilerAdapter
from app.compiler.service import CertifiedIntentCompiler
from app.execution import (
    DuckDBGateway,
    ExecutionLimits,
    ExecutionResultStore,
    GatewayCostEstimator,
    GatewayExecutor,
    run_control_totals,
    validate_result,
)
from app.runtime import (
    AgentGraphRunner,
    BootstrapRequest,
    analytics_plan_node,
    certified_intent_node,
    compile_node,
    context_retrieval_node,
    estimate_node,
    fake_execution_node,
    governed_graph_v2,
    identity_bootstrap_node,
    ontology_resolution_node,
    policy_node,
    result_validation_node,
    review_decision_node,
    structured_intent_node,
)
from app.runtime.clarification import clarification_node
from app.runtime.evidence import EvidenceBuildError, build_evidence_envelope
from app.runtime.evidence_store import (
    EvidenceChainError,
    EvidenceConflictError,
    EvidenceNotFoundError,
    EvidenceStore,
    EvidenceStoreError,
    record_terminal_evidence,
)
from app.runtime.governed_stages import CompiledPlanStore, PolicyValueStore
from packages.platform_contracts.analytics_intent import AnalyticalIntent
from packages.platform_contracts.evidence import EvidenceEnvelope, EvidenceEnvelopeBody
from packages.platform_contracts.security import AnalyticsIdentity


@pytest.fixture
def stores(tmp_path, monkeypatch):
    control = _database(tmp_path, monkeypatch)
    return control, EvidenceStore(control.engine)


def _seal(control, evidence, case_id, **kwargs):
    result = _execute_case(case_id, _state(case_id), control, FakeExecutor())
    return result.state, record_terminal_evidence(control, evidence, result.state, **kwargs)


# ---- every non-success terminal outcome carries its required evidence ----

REQUIRED = {
    "refuse_identity": ("refused", "policy_denied"),
    "refuse_policy": ("refused", "policy_denied"),
    "review_expired": ("review_required", None),
    "stale_context": ("review_required", "stale_context"),
    "malformed_intent": ("failed", None),
    "cost_budget": ("failed", None),
    "deadline": ("failed", None),
    "cycle": ("failed", None),
    "cancel": ("cancelled", None),
}


@pytest.mark.parametrize("case_id", sorted(REQUIRED))
def test_each_terminal_outcome_is_sealed_with_provenance(stores, case_id):
    control, evidence = stores
    state, appended = _seal(control, evidence, case_id)
    envelope = evidence.get(state.run_id, tenant_id=TENANT, purpose=PURPOSE)
    kind, code = REQUIRED[case_id]
    assert appended.created and envelope.terminal_kind == kind
    assert envelope.context_snapshot_id == state.context_snapshot_id and envelope.request_id == state.request_id
    assert envelope.transitions[-1].to_status == "terminal" and envelope.terminal_evidence_fingerprints
    if code:
        assert code in {error.code for error in envelope.errors}
    if kind == "cancelled":
        assert envelope.cancellation and envelope.cancellation.policy_source == "test-harness"
    if case_id == "refuse_policy":
        assert envelope.policy.effect == "deny" and envelope.policy.reasons
    assert envelope.errors or envelope.cancellation


def test_policy_denial_evidence_holds_no_sensitive_values(stores):
    control, evidence = stores
    state, _ = _seal(control, evidence, "refuse_policy")
    raw = evidence.get(state.run_id, tenant_id=TENANT, purpose=PURPOSE).model_dump_json()
    assert "SELECT" not in raw and "policy_values_reference" not in raw


def test_review_rejected_is_refused_and_review_approved_needs_result_evidence(stores):
    control, evidence = stores
    state, _ = _seal(control, evidence, "review_rejected")
    sealed = evidence.get(state.run_id, tenant_id=TENANT, purpose=PURPOSE)
    assert sealed.terminal_kind == "refused" and sealed.cost.requires_approval
    # The stub graph never validated a result, so a "succeeded" run cannot be sealed.
    result = _execute_case("answer", _state("answer"), control, FakeExecutor())
    with pytest.raises(ValidationError, match="succeeded evidence is incomplete"):
        record_terminal_evidence(control, evidence, result.state)
    with pytest.raises(EvidenceNotFoundError):
        evidence.get(result.state.run_id, tenant_id=TENANT, purpose=PURPOSE)


# ---- a real succeeded run: DuckDB execution, result validation, sealed ----


def _real_answer_runner(control, tmp_path, explain=None):
    connection = duckdb.connect()
    connection.execute("""CREATE TABLE sales_orders AS SELECT 'o' || i AS id, CAST(i AS DECIMAL(12,2)) AS amount,
        CASE WHEN i % 5 = 0 THEN 'refunded' ELSE 'paid' END AS status,
        TIMESTAMP '2024-01-01' + INTERVAL (i * 20) HOUR AS created_at FROM range(1, 101) t(i)""")
    connection.execute(f"COPY sales_orders TO '{tmp_path / 'sales_orders.parquet'}' (FORMAT PARQUET)")
    connection.close()
    gateway = DuckDBGateway({"sales_orders": tmp_path / "sales_orders.parquet"}, allowed_root=tmp_path)
    gateways = {"duckdb": gateway}
    document = _registry_document()
    context, ontology = _context(document)
    plans, results, policy_values = CompiledPlanStore(), ExecutionResultStore(), PolicyValueStore()
    compiler = CertifiedIntentCompiler(SERVICE_ROOT / "semantic_registry", adapter=DuckDBCompilerAdapter())
    identity = AnalyticsIdentity(tenant_id=TENANT, user_id="requester", purposes=[PURPOSE], groups=["analyst"])
    request = BootstrapRequest(request_id="real", request_text="Show monthly revenue", identity=identity)
    contracts = ContractsProvider(document)

    def controls(node_input, intent, contract):
        return run_control_totals(
            intent, contract, compile_plan=lambda i, c: compiler.compile(i), gateway=gateway, limits=ExecutionLimits()
        )

    def output(ni, nxt):
        from packages.platform_contracts.agent_runtime import NodeOutput

        return NodeOutput(run_id=ni.run_id, node_id=ni.node_id, status="completed", next_node=nxt)

    handlers = {
        "create": lambda ni: output(ni, "bootstrap"),
        "bootstrap": identity_bootstrap_node(request),
        "retrieve": context_retrieval_node(SnapshotProvider(context), SearchProvider()),
        "extract_intent": structured_intent_node(IntentClient(_intent("real"))),
        "resolve": ontology_resolution_node(contracts, OntologyProvider(ontology)),
        "clarify": clarification_node(),
        "plan": analytics_plan_node(contracts),
        "validate": certified_intent_node(contracts),
        "policy": policy_node(contracts, identity, policy_values, review_store=control),
        "compile": compile_node(compiler, plans, policy_values),
        "estimate": estimate_node(
            plans,
            GatewayCostEstimator(gateways),
            approval_threshold=1e9,
            review_store=control,
            requested_by=identity.user_id,
        ),
        "approve": review_decision_node(control),
        "execute": fake_execution_node(GatewayExecutor(plans, gateways, results, ExecutionLimits())),
        "result_validate": result_validation_node(plans, results, contracts, controls),
        "explain": explain(plans, results, contracts) if explain else (lambda ni: output(ni, "terminal")),
    }
    runner = AgentGraphRunner(control, governed_graph_v2(handlers), now=lambda: NOW)
    return runner, plans, results, controls, contracts


def test_real_successful_run_is_sealed_with_result_validation_and_policy_evidence(stores, tmp_path):
    control, evidence = stores
    runner, plans, results, controls, contracts = _real_answer_runner(control, tmp_path)
    outcome = runner.start(_state("real"), owner_id="w", lease_token="lease-real")
    state = outcome.state
    assert state.terminal_outcome.kind == "succeeded", (state.errors, state.current_node)

    intent = AnalyticalIntent.model_validate(state.intent)
    plan = plans.get(TENANT, state.run_id, state.compiled_plan_reference)
    result = results.get(TENANT, state.run_id, state.execution_reference)
    report = validate_result(
        result,
        plan,
        intent,
        contracts.get_certified("sales-core", "v1").contract,
        control_totals=controls(None, intent, contracts.get_certified("sales-core", "v1").contract),
    )
    assert report.status == "valid"

    appended = record_terminal_evidence(control, evidence, state, validation=report)
    sealed = evidence.get(state.run_id, tenant_id=TENANT, purpose=PURPOSE)
    assert appended.chain_seq == 1 and sealed.terminal_kind == "succeeded"
    assert sealed.policy.effect == "allow" and sealed.cost.estimated_cost_units > 0
    assert sealed.result.validation_status == "valid" and sealed.result.row_count == result.row_count
    assert sealed.result.result_fingerprint == report.result_fingerprint
    assert sealed.semantic_contract == "sales-core@v1" and sealed.intent_fingerprint
    assert "sales_orders" not in sealed.model_dump_json()  # no SQL, table names, or rows
    assert [t.sequence for t in sealed.transitions] == list(range(1, len(sealed.transitions) + 1))

    # A report computed for some other result is not bound to this run's recorded evidence.
    other = validate_result(
        result.__class__(**{**result.__dict__, "rows": result.rows[:-1]}),
        plan,
        intent,
        contracts.get_certified("sales-core", "v1").contract,
        require_control_totals=False,
    )
    with pytest.raises(EvidenceBuildError, match="not bound"):
        build_evidence_envelope(
            state, control.replay_transitions(run_id=state.run_id, tenant_id=TENANT, purpose=PURPOSE), validation=other
        )


# ---- contract-level enforcement ----


def _body(**overrides):
    base = {
        "tenant_id": "t",
        "run_id": "r",
        "request_id": "q",
        "purpose": "p",
        "graph_version": "graph-v2",
        "terminal_kind": "failed",
        "context_snapshot_id": "s",
        "errors": [{"code": "boom", "reference": "r:boom"}],
        "transitions": [
            {"sequence": 1, "from_node": "create", "to_node": "bootstrap", "to_status": "active"},
            {"sequence": 2, "from_node": "bootstrap", "to_node": None, "to_status": "terminal"},
        ],
        "terminal_summary_reference": "r:terminal",
        "terminal_evidence_fingerprints": ["f" * 64],
        "completed_at": datetime(2026, 10, 1, tzinfo=timezone.utc),
    }
    base.update(overrides)
    return base


def test_required_evidence_per_terminal_kind_is_enforced_by_the_model():
    assert EvidenceEnvelope.build(**_body()).envelope_id.startswith("evidence:")
    for kind in ("failed", "refused", "review_required", "clarification_required", "cancelled", "succeeded"):
        with pytest.raises(ValidationError, match="incomplete"):
            EvidenceEnvelope.build(**_body(terminal_kind=kind, errors=[]))
    assert EvidenceEnvelope.build(
        **_body(terminal_kind="refused", errors=[{"code": "policy_denied", "reference": "x"}])
    )
    with pytest.raises(ValidationError, match="incomplete"):
        EvidenceEnvelope.build(**_body(terminal_kind="refused"))  # an unrelated error is not a refusal
    assert EvidenceEnvelope.build(
        **_body(
            terminal_kind="clarification_required",
            errors=[],
            clarification={"ambiguity_codes": ["metric"], "continuation_count": 1},
        )
    )


def test_envelope_rejects_gaps_non_terminal_ends_naive_time_and_forged_fingerprints():
    with pytest.raises(ValidationError, match="contiguous"):
        EvidenceEnvelope.build(
            **_body(transitions=[{"sequence": 2, "from_node": "a", "to_node": None, "to_status": "terminal"}])
        )
    with pytest.raises(ValidationError, match="terminal transition"):
        EvidenceEnvelope.build(
            **_body(transitions=[{"sequence": 1, "from_node": "a", "to_node": "b", "to_status": "active"}])
        )
    with pytest.raises(ValidationError, match="timezone"):
        EvidenceEnvelope.build(**_body(completed_at=datetime(2026, 10, 1)))
    good = EvidenceEnvelope.build(**_body())
    forged = good.model_dump()
    forged["terminal_summary_reference"] = "r:other"
    with pytest.raises(ValidationError, match="content_fingerprint"):
        EvidenceEnvelope.model_validate(forged)
    assert EvidenceEnvelopeBody(**_body()).compute_fingerprint() == good.content_fingerprint


# ---- append-only, tenant-scoped, hash-chained storage ----


def test_chain_links_runs_is_idempotent_and_tenant_scoped(stores):
    control, evidence = stores
    sealed = [_seal(control, evidence, case)[0] for case in ("refuse_identity", "stale_context", "cancel")]
    assert evidence.verify_chain(TENANT) == 3 and evidence.verify_chain("tenant-empty") == 0
    with evidence.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT chain_seq, previous_hash, chain_hash FROM analytics_evidence_envelopes ORDER BY chain_seq")
        ).all()
    assert [row[0] for row in rows] == [1, 2, 3] and rows[0][1] is None
    assert rows[1][1] == rows[0][2] and rows[2][1] == rows[1][2]
    again = record_terminal_evidence(control, evidence, sealed[0])
    assert not again.created and again.chain_seq == 1 and evidence.verify_chain(TENANT) == 3
    with pytest.raises(EvidenceNotFoundError):
        evidence.get(sealed[0].run_id, tenant_id="tenant-b", purpose=PURPOSE)
    with pytest.raises(EvidenceNotFoundError):
        evidence.get(sealed[0].run_id, tenant_id=TENANT, purpose="other-purpose")


def test_a_different_envelope_for_a_sealed_run_conflicts_and_nonterminal_runs_cannot_be_sealed(stores):
    control, evidence = stores
    state, _ = _seal(control, evidence, "stale_context")
    original = evidence.get(state.run_id, tenant_id=TENANT, purpose=PURPOSE)
    changed = EvidenceEnvelope.build(
        **{**original.model_dump(exclude={"content_fingerprint"}), "terminal_summary_reference": "x"}
    )
    with pytest.raises(EvidenceConflictError):
        evidence.append(changed)
    pending = _execute_case("review_pending", _state("review_pending"), control, FakeExecutor())
    assert pending.state.status != "terminal"
    ghost = EvidenceEnvelope.build(
        **{**original.model_dump(exclude={"content_fingerprint"}), "run_id": pending.state.run_id}
    )
    with pytest.raises(EvidenceStoreError, match="terminal run"):
        evidence.append(ghost)
    unknown = EvidenceEnvelope.build(
        **{**original.model_dump(exclude={"content_fingerprint"}), "run_id": "no-such-run"}
    )
    with pytest.raises(EvidenceStoreError):
        evidence.append(unknown)


def test_store_rejects_mutation_and_verification_detects_tampering(stores):
    control, evidence = stores
    state, _ = _seal(control, evidence, "stale_context")
    _seal(control, evidence, "cancel")
    for statement in (
        "UPDATE analytics_evidence_envelopes SET terminal_kind='succeeded'",
        "DELETE FROM analytics_evidence_envelopes",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            with evidence.engine.begin() as connection:
                connection.execute(text(statement))
    assert evidence.verify_chain(TENANT) == 2
    with evidence.engine.begin() as connection:  # an operator with schema rights bypasses the trigger
        connection.execute(text("DROP TRIGGER trg_evidence_envelopes_no_update"))
        connection.execute(
            text("UPDATE analytics_evidence_envelopes SET content_fingerprint=:f WHERE chain_seq=1"), {"f": "0" * 64}
        )
    with pytest.raises(EvidenceChainError, match="sequence 1"):
        evidence.verify_chain(TENANT)
