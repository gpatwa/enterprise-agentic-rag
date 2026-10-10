"""Typed, dialect-neutral analytical intent for certified semantic contracts."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from packages.platform_contracts.semantic import SemanticContract

ANALYTICAL_INTENT_VERSION = "v1"
Scalar = str | int | float | bool


class IntentModel(BaseModel):
    """Reject undeclared fields, including raw SQL, from planner output."""

    model_config = ConfigDict(extra="forbid")


class SemanticContractReference(IntentModel):
    contract_id: str = Field(min_length=1, max_length=255)
    contract_version: str = Field(min_length=1, max_length=255)


class IntentMetric(IntentModel):
    metric_id: str = Field(min_length=1, max_length=255)
    alias: str | None = Field(default=None, min_length=1, max_length=255)


class IntentGrouping(IntentModel):
    dimension_id: str = Field(min_length=1, max_length=255)
    time_granularity: Literal["day", "week", "month", "quarter", "year"] | None = None


class IntentTimeRange(IntentModel):
    dimension_id: str = Field(min_length=1, max_length=255)
    start: datetime | None = None
    end: datetime | None = None
    inclusive_end: bool = True

    @model_validator(mode="after")
    def validate_bounds(self) -> "IntentTimeRange":
        if self.start and self.end and self.start > self.end:
            raise ValueError("time range start must be before or equal to end")
        return self


class IntentFilter(IntentModel):
    field_id: str = Field(min_length=1, max_length=255)
    operator: Literal[
        "equals",
        "not_equals",
        "in",
        "not_in",
        "greater_than",
        "greater_than_or_equal",
        "less_than",
        "less_than_or_equal",
    ]
    values: list[Scalar] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_operator_values(self) -> "IntentFilter":
        if self.operator in {"in", "not_in"} and len(self.values) < 1:
            raise ValueError(f"{self.operator} filters require one or more values")
        if self.operator not in {"in", "not_in"} and len(self.values) != 1:
            raise ValueError(f"{self.operator} filters require exactly one value")
        return self


class IntentSort(IntentModel):
    target_kind: Literal["metric", "dimension"]
    target_id: str = Field(min_length=1, max_length=255)
    direction: Literal["asc", "desc"] = "asc"


class AnalyticalIntent(IntentModel):
    """A semantic request that is independent of database and SQL dialect."""

    intent_version: Literal[ANALYTICAL_INTENT_VERSION] = ANALYTICAL_INTENT_VERSION
    query_id: str = Field(min_length=1, max_length=255)
    tenant_id: str = Field(min_length=1, max_length=255)
    dataset_id: str = Field(min_length=1, max_length=255)
    semantic_contract: SemanticContractReference
    metrics: list[IntentMetric] = Field(min_length=1, max_length=10)
    group_by: list[IntentGrouping] = Field(default_factory=list, max_length=10)
    time_range: IntentTimeRange | None = None
    filters: list[IntentFilter] = Field(default_factory=list, max_length=20)
    sort: list[IntentSort] = Field(default_factory=list, max_length=5)
    limit: int = Field(default=100, ge=1, le=1_000)

    @model_validator(mode="after")
    def validate_shape(self) -> "AnalyticalIntent":
        metric_ids = [metric.metric_id for metric in self.metrics]
        if len(metric_ids) != len(set(metric_ids)):
            raise ValueError("intent metric IDs must be unique")
        dimension_ids = [grouping.dimension_id for grouping in self.group_by]
        if len(dimension_ids) != len(set(dimension_ids)):
            raise ValueError("intent grouping dimension IDs must be unique")
        for sort in self.sort:
            selected_ids = metric_ids if sort.target_kind == "metric" else dimension_ids
            if sort.target_id not in selected_ids:
                raise ValueError(f"sort target {sort.target_id} is not selected by the intent")
        return self

    def validate_against(self, contract: SemanticContract) -> "AnalyticalIntent":
        """Confirm all IDs and scope belong to one exact semantic contract."""
        if contract.id != self.semantic_contract.contract_id:
            raise ValueError("intent semantic contract ID does not match the supplied contract")
        if contract.version != self.semantic_contract.contract_version:
            raise ValueError("intent semantic contract version does not match the supplied contract")
        if contract.tenant_id != self.tenant_id:
            raise ValueError("intent tenant does not match the supplied contract")
        if self.dataset_id not in {dataset.id for dataset in contract.datasets}:
            raise ValueError("intent dataset is not defined by the supplied contract")

        _require_selected_ids("intent metric", [metric.metric_id for metric in self.metrics], contract.metrics)
        _require_selected_ids("intent grouping", [group.dimension_id for group in self.group_by], contract.dimensions)
        _require_selected_ids("intent filter", [filter_.field_id for filter_ in self.filters], contract.fields)
        if self.time_range:
            _require_selected_ids("intent time range", [self.time_range.dimension_id], contract.dimensions)
            time_dimension = next(
                dimension
                for dimension in contract.dimensions
                if dimension.id == self.time_range.dimension_id
            )
            if time_dimension.dimension_type != "temporal":
                raise ValueError("intent time range must reference a temporal dimension")
        return self


def _require_selected_ids(kind: str, selected_ids: list[str], available: list[BaseModel]) -> None:
    available_ids = {item.id for item in available}
    missing = sorted(identifier for identifier in selected_ids if identifier not in available_ids)
    if missing:
        raise ValueError(f"unknown {kind} ID(s): {', '.join(missing)}")
