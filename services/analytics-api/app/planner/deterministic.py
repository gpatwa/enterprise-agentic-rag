"""Small deterministic planner used as a governed baseline and test oracle."""
from __future__ import annotations

import re

from packages.platform_contracts.analytics_intent import (
    AnalyticalIntent,
    IntentGrouping,
    IntentMetric,
    SemanticContractReference,
)
from packages.platform_contracts.analytics_planning import (
    AnalyticsAmbiguity,
    AnalyticsContextCitation,
    AnalyticsPlan,
)
from packages.platform_contracts.semantic import SemanticContract


class PlanningError(ValueError):
    def __init__(self, ambiguities: list[AnalyticsAmbiguity]):
        self.ambiguities = ambiguities
        super().__init__("analytical request requires clarification")


class DeterministicIntentPlanner:
    version = "deterministic-v1"

    def plan(self, query: str, *, query_id: str, tenant_id: str, contract: SemanticContract) -> AnalyticsPlan:
        terms = set(re.findall(r"[a-z0-9]+", query.lower()))
        metric = self._match_one(terms, contract.metrics, "metric")
        dataset = contract.datasets[0]
        dimensions = [dimension for dimension in contract.dimensions if dimension.dataset_id == dataset.id]
        time_dimension = next((dimension for dimension in dimensions if dimension.dimension_type == "temporal"), None)
        if metric is None or time_dimension is None:
            ambiguities = []
            if metric is None:
                ambiguities.append(AnalyticsAmbiguity(code="metric", prompt="Which certified metric should I use?", candidate_ids=[item.id for item in contract.metrics]))
            if time_dimension is None:
                ambiguities.append(AnalyticsAmbiguity(code="time", prompt="Which time dimension should I use?", candidate_ids=[] or [dimension.id for dimension in dimensions]))
            raise PlanningError(ambiguities)
        intent = AnalyticalIntent(
            query_id=query_id,
            tenant_id=tenant_id,
            dataset_id=dataset.id,
            semantic_contract=SemanticContractReference(contract_id=contract.id, contract_version=contract.version),
            metrics=[IntentMetric(metric_id=metric.id)],
            group_by=[IntentGrouping(dimension_id=time_dimension.id, time_granularity="month")],
        )
        context = [
            AnalyticsContextCitation(asset_id=contract.id, asset_type="semantic_contract", version=contract.version, reason="certified contract selected"),
            AnalyticsContextCitation(asset_id=metric.id, asset_type="metric", version=contract.version, reason="metric selected from request terms"),
            AnalyticsContextCitation(asset_id=time_dimension.id, asset_type="dimension", version=contract.version, reason="temporal grouping selected"),
        ]
        return AnalyticsPlan(query_id=query_id, intent=intent, context=context, planner_version=self.version)

    @staticmethod
    def _match_one(terms: set[str], values, kind: str):
        matches = [
            value
            for value in values
            if value.id.lower() in terms
            or set(value.id.lower().split("_")) <= terms
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise PlanningError([AnalyticsAmbiguity(code=kind, prompt=f"Which {kind} should I use?", candidate_ids=[item.id for item in matches])])
        return None
