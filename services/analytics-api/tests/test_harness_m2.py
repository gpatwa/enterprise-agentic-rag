from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.harness import (
    FakeCatalogProvider,
    FakeIdentityProvider,
    FakeModelProvider,
    FakePolicyProvider,
    FakeSemanticRegistryProvider,
    FakeWarehouseProvider,
    build_deterministic_report,
)
from packages.platform_contracts.determinism import DeterministicBudgetExceeded, DeterministicControls
from packages.platform_contracts.harness import ExpectedTrace, ExpectedTraceStep, HarnessScenario
from packages.platform_contracts.metadata import MetadataSnapshot
from packages.platform_contracts.security import AnalyticsIdentity, AuthorizationDecision
from packages.platform_contracts.semantic import (
    SemanticContract,
    SemanticDataset,
    SemanticField,
    SemanticGrain,
    SemanticMetric,
    SemanticOwner,
    SemanticRegistryDocument,
)


def expected_trace() -> ExpectedTrace:
    return ExpectedTrace(
        graph_version="graph-v1",
        steps=(
            ExpectedTraceStep(sequence=1, from_node="create", to_node="bootstrap", to_status="active"),
            ExpectedTraceStep(sequence=2, from_node="bootstrap", to_node="retrieve", to_status="active"),
            ExpectedTraceStep(sequence=3, from_node="retrieve", to_node="resolve", to_status="active"),
            ExpectedTraceStep(sequence=4, from_node="resolve", to_node="plan", to_status="active"),
            ExpectedTraceStep(sequence=5, from_node="plan", to_node="validate", to_status="active"),
            ExpectedTraceStep(sequence=6, from_node="validate", to_node="compile", to_status="active"),
            ExpectedTraceStep(sequence=7, from_node="compile", to_node="policy", to_status="active"),
            ExpectedTraceStep(sequence=8, from_node="policy", to_node=None, to_status="terminal"),
        ),
        terminal_kind="succeeded",
    )


def scenario() -> HarnessScenario:
    return HarnessScenario.build(
        scenario_id="scenario-1", tenant_id="demo", purpose="analytics",
        request="Show revenue by month", context_snapshot_id="snapshot-1",
        graph_version="graph-v1", expected_trace=expected_trace(),
        inputs={"dataset": "orders"},
    )


def test_scenario_is_versioned_content_addressed_and_round_trips():
    current = scenario()
    assert HarnessScenario.model_validate_json(current.model_dump_json()) == current
    forged = current.model_dump()
    forged["fixture_digest"] = "a" * 64
    with pytest.raises(ValidationError, match="fixture_digest"):
        HarnessScenario(**forged)


def test_expected_trace_rejects_disconnected_or_illegal_steps():
    with pytest.raises(ValidationError, match="connect in order"):
        ExpectedTrace(
            graph_version="graph-v1",
            steps=(
                ExpectedTraceStep(sequence=1, from_node="create", to_node="bootstrap", to_status="active"),
                ExpectedTraceStep(sequence=2, from_node="policy", to_node=None, to_status="terminal"),
            ),
            terminal_kind="failed",
        )
    with pytest.raises(ValidationError, match="illegal expected transition"):
        ExpectedTraceStep(sequence=1, from_node="create", to_node="execute", to_status="active")


def test_provider_fakes_are_deterministic_and_tenant_scoped():
    identity = AnalyticsIdentity(tenant_id="demo", user_id="user-1")
    identities = FakeIdentityProvider({("demo", "user-1"): identity})
    assert identities.resolve("demo", "user-1") == identity

    catalog = FakeCatalogProvider({"orders": MetadataSnapshot(provider="fake", assets=[])})
    assert catalog.get_snapshot("orders").provider == "fake"

    contract = SemanticContract(
        id="sales", tenant_id="demo", domain="commerce", version="v1",
        owners=[SemanticOwner(id="team", display_name="Team", owner_type="team")],
        datasets=[SemanticDataset(
            id="orders", display_name="Orders", source_asset_id="orders", physical_name="orders",
            description="Orders", owner_ids=["team"],
        )],
        fields=[SemanticField(id="orders.amount", dataset_id="orders", physical_name="amount", data_type="decimal")],
        metrics=[SemanticMetric(
            id="revenue", dataset_id="orders", aggregation="sum", measure_field_id="orders.amount",
            grain=SemanticGrain(kind="order", key_field_ids=["orders.amount"]), owner_ids=["team"],
        )],
    )
    registry = FakeSemanticRegistryProvider({("sales", "v1"): SemanticRegistryDocument(lifecycle="certified", contract=contract)})
    assert registry.get_contract("sales", "v1").id == "sales"

    model = FakeModelProvider({"prompt": {"metric_id": "revenue"}})
    assert model.complete("prompt") == {"metric_id": "revenue"}
    decision = AuthorizationDecision(decision_id="decision-1", effect="allow", reasons=["test"], policy_version="v1")
    assert FakePolicyProvider({("demo", "analytics"): decision}).decide("demo", "analytics") == decision
    warehouse = FakeWarehouseProvider({"SELECT 1": [{"value": 1}]})
    assert warehouse.execute("SELECT 1") == [{"value": 1}]


def test_deterministic_controls_repeat_semantic_report_and_enforce_budget():
    first = build_deterministic_report(scenario(), DeterministicControls.from_seed("seed-1"))
    second = build_deterministic_report(scenario(), DeterministicControls.from_seed("seed-1"))
    different = build_deterministic_report(scenario(), DeterministicControls.from_seed("seed-2"))
    assert first == second
    assert first.semantic_fingerprint != different.semantic_fingerprint
    assert first.logical_time == datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
    with pytest.raises(DeterministicBudgetExceeded, match="token budget"):
        build_deterministic_report(
            scenario(), DeterministicControls.from_seed("seed", max_tokens=1)
        )
