"""Operations dashboard contracts (ADS-069). Everything here is a count, an id, a code, or a status: never request text or rows."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


GateStatus = Literal["passing", "failing", "unapproved", "missing"]


class DashboardAlert(_Frozen):
    source: Literal["quota", "slo", "drift", "gate", "run"]
    kind: str
    severity: Literal["warning", "page"]
    subject: str  # a tenant id, a gate id, or a run_ref
    value: float | None = None
    threshold: float | None = None
    runbook_id: str = Field(pattern=r"^(ops|drift)-[a-z-]+$")


class GateRow(_Frozen):
    gate_id: str
    packet: str
    status: GateStatus
    approval_status: str | None  # echoed from the evidence file; the dashboard never sets or infers an approval
    detail: str
    runbook_id: str = Field(pattern=r"^ops-[a-z-]+$")


class TenantRow(_Frozen):
    tenant_id: str
    in_flight: int = Field(ge=0)
    admitted: int = Field(ge=0)
    rate_limited: int = Field(ge=0)
    day_cost_units: float = Field(ge=0)
    cost_by_purpose: dict[str, float] = {}


class Dashboard(_Frozen):
    generated_for: str  # the run or drill this snapshot belongs to; a label, not a time
    tenants: tuple[TenantRow, ...]
    alerts: tuple[DashboardAlert, ...]
    gates: tuple[GateRow, ...]
    open_findings: tuple[str, ...]  # security finding ids that are not resolved

    @property
    def paging(self) -> tuple[DashboardAlert, ...]:
        return tuple(a for a in self.alerts if a.severity == "page")


class RunDiagnosis(_Frozen):
    """A read-only account of one run: where it stopped and why, from durable records only."""

    run_ref: str
    status: str
    terminal_kind: str | None
    last_node: str | None
    path: tuple[str, ...]
    history_contiguous: bool
    evidence_ids: tuple[str, ...]
    runbook_id: str = Field(pattern=r"^ops-[a-z-]+$")

    def digest(self) -> str:
        import hashlib

        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()
