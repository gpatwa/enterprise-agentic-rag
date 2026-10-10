"""EA-030 to EA-033 deterministic planner and clarification tests."""
import json
from pathlib import Path

import pytest

from app.planner import DeterministicIntentPlanner, PlanningError
from packages.platform_contracts.semantic import SemanticContract

CONTRACT = Path(__file__).parent.parent / "semantic_registry/contracts/olist-commerce-v1.json"


def contract():
    return SemanticContract.model_validate(json.loads(CONTRACT.read_text())["contract"])


def test_planner_emits_typed_intent_and_citations():
    plan = DeterministicIntentPlanner().plan("show delivered revenue by month", query_id="q1", tenant_id="demo", contract=contract())
    assert plan.intent.metrics[0].metric_id == "delivered_revenue"
    assert plan.intent.group_by[0].time_granularity == "month"
    assert {citation.asset_type for citation in plan.context} == {"semantic_contract", "metric", "dimension"}


def test_planner_refuses_to_guess_missing_metric():
    with pytest.raises(PlanningError) as error:
        DeterministicIntentPlanner().plan("show results by month", query_id="q1", tenant_id="demo", contract=contract())
    assert error.value.ambiguities[0].code == "metric"
