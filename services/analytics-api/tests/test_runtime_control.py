"""EA-050, EA-053, EA-054, and EA-058 control/runtime tests."""
import pytest

from app.runtime import CancellationRegistry, GatewayRegistration, GatewayRegistry, UsageMeter
from packages.platform_contracts.runtime import QueryTelemetry, UsageRecord


def test_gateway_registry_routes_only_one_healthy_tenant_gateway():
    registry = GatewayRegistry()
    registry.register(GatewayRegistration("gw-1", "demo", "postgres", "v1"))
    assert registry.route("demo", "postgres").gateway_id == "gw-1"
    registry.register(GatewayRegistration("gw-2", "demo", "postgres", "v1"))
    with pytest.raises(LookupError):
        registry.route("demo", "postgres")


def test_cancellation_and_usage_meter_are_tenant_scoped():
    cancellation = CancellationRegistry()
    cancellation.cancel("q-1")
    assert cancellation.is_cancelled("q-1") is True
    assert cancellation.is_cancelled("q-2") is False

    meter = UsageMeter()
    meter.record(UsageRecord(query_id="q-1", tenant_id="demo", model_units=2, warehouse_units=3, duration_ms=10))
    meter.record(UsageRecord(query_id="q-2", tenant_id="other", model_units=9))
    meter.emit(QueryTelemetry(query_id="q-1", tenant_id="demo", trace_id="t", stage="completed", duration_ms=10))
    assert meter.total_for_tenant("demo").warehouse_units == 3
    assert len(meter.telemetry) == 1
