"""ADS-078: a second tenant onboards from an Ossie model with no code or schema change, safely, and each gate can fail."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from reference_stack import onboarding_eval as ev

from app.semantic_registry import SemanticRegistry
from packages.platform_contracts.ossie import import_ossie

THRESHOLDS = json.loads(ev.THRESHOLDS.read_text())


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    return ev.run_onboarding(root=tmp_path_factory.mktemp("onboarding"))


def test_every_gate_is_met_and_the_thresholds_are_proposed(report):
    assert report["ok"], [(n, g["value"]) for n, g in report["gates"].items() if not g["meets"]]
    assert THRESHOLDS["approval"]["status"] == "proposed" and all(s["ok"] for s in report["steps"])


def test_the_import_is_a_draft_that_is_not_certification_eligible():
    document, r = import_ossie(ev.OSSIE_MODEL, tenant_id="tenant-b", source_reference="t")
    assert document.lifecycle == "draft" and not r.certification_eligible and document.contract.policies == []


def test_a_draft_in_a_registry_is_never_served(tmp_path):
    document, _ = import_ossie(ev.OSSIE_MODEL, tenant_id="tenant-b", source_reference="t")
    (tmp_path / "subs-draft.json").write_text(document.model_dump_json())
    with pytest.raises(LookupError):
        SemanticRegistry(tmp_path).get_certified(document.contract.id, document.contract.version)


def test_the_drill_never_writes_the_repository_registry(report):
    registry = ev.SERVICE_ROOT / "semantic_registry"
    assert sorted(p.name for p in registry.rglob("*.json")) == ["olist-commerce-v1.json", "sales-core-v1.json"]
    assert not any("subscriptions" in p.name for p in Path(registry).rglob("*"))


def test_the_export_now_carries_metrics_and_time_dimensions(report):
    assert report["gates"]["round_trip_omissions"]["value"] == 0
    text = ev.render_markdown(report)
    assert "not a certification" in text and "What a person must still do" in text


def test_hostile_ossie_expressions_are_dropped(report):
    step = next(s for s in report["steps"] if "hostile" in s["step"])
    assert step["ok"] and "mrr" in step["detail"] and "injected" not in step["detail"]


def test_a_code_change_would_be_detected(monkeypatch, tmp_path):
    calls = {"n": 0}
    original = ev._source_digest

    def moving():
        calls["n"] += 1
        return original() + ("x" if calls["n"] > 1 else "")  # as if a file changed during onboarding

    monkeypatch.setattr(ev, "_source_digest", moving)
    result = ev.run_onboarding(root=tmp_path)
    assert result["gates"]["code_and_schema_changes"]["value"] == 1 and not result["ok"]


def test_a_wrong_second_tenant_answer_fails_the_equivalence_gate(monkeypatch, tmp_path):
    real = ev._seed_subs
    monkeypatch.setattr(ev, "_seed_subs", lambda d: (real(d)[0], [["2025-02-01", "1"]]))
    result = ev.run_onboarding(root=tmp_path)
    assert result["gates"]["second_tenant_result_equivalence"]["value"] == 0.0 and not result["ok"]


def test_a_certification_gate_that_accepts_everything_fails_the_isolation_gate(monkeypatch, tmp_path):
    from packages.platform_contracts.agent_runtime import NodeOutput

    def accept_all(registry, **kwargs):
        return lambda node_input: NodeOutput(
            run_id=node_input.run_id, node_id=node_input.node_id, status="completed", next_node="compile"
        )

    monkeypatch.setattr(ev, "certified_intent_node", accept_all)
    result = ev.run_onboarding(root=tmp_path)
    assert result["gates"]["cross_tenant_contract_use"]["value"] == 2 and not result["ok"]
