"""Local control/data-plane protocol primitives."""
from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Protocol

from packages.platform_contracts.runtime import QueryTelemetry, RuntimeQueryRequest, UsageRecord


class ExecutionGateway(Protocol):
    def execute(self, request: RuntimeQueryRequest, sql: str, parameters: dict) -> dict:
        ...


@dataclass(frozen=True)
class GatewayRegistration:
    gateway_id: str
    tenant_id: str
    dialect: str
    version: str
    healthy: bool = True


class GatewayRegistry:
    def __init__(self):
        self._registrations: dict[str, GatewayRegistration] = {}

    def register(self, registration: GatewayRegistration) -> None:
        self._registrations[registration.gateway_id] = registration

    def route(self, tenant_id: str, dialect: str) -> GatewayRegistration:
        matches = [item for item in self._registrations.values() if item.tenant_id == tenant_id and item.dialect == dialect and item.healthy]
        if len(matches) != 1:
            raise LookupError("healthy execution gateway is not uniquely available")
        return matches[0]


class CancellationRegistry:
    def __init__(self):
        self._cancelled: set[str] = set()
        self._lock = Lock()

    def cancel(self, cancellation_key: str) -> None:
        with self._lock:
            self._cancelled.add(cancellation_key)

    def is_cancelled(self, cancellation_key: str) -> bool:
        with self._lock:
            return cancellation_key in self._cancelled


class UsageMeter:
    def __init__(self):
        self.records: list[UsageRecord] = []
        self.telemetry: list[QueryTelemetry] = []

    def record(self, usage: UsageRecord) -> None:
        self.records.append(usage)

    def emit(self, event: QueryTelemetry) -> None:
        self.telemetry.append(event)

    def total_for_tenant(self, tenant_id: str) -> UsageRecord:
        records = [record for record in self.records if record.tenant_id == tenant_id]
        return UsageRecord(
            query_id="tenant-total",
            tenant_id=tenant_id,
            model_units=sum(record.model_units for record in records),
            warehouse_units=sum(record.warehouse_units for record in records),
            duration_ms=sum(record.duration_ms for record in records),
        )
