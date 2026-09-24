"""Provider fakes and deterministic scenario probes for local harness work."""

from app.harness.fakes import (
    FakeCatalogProvider,
    FakeIdentityProvider,
    FakeModelProvider,
    FakePolicyProvider,
    FakeSemanticRegistryProvider,
    FakeWarehouseProvider,
)
from app.harness.faults import FaultPlan, FaultSpec
from app.harness.graph import TERMINAL_NODE, GraphExecutionResult, GraphHarness, GraphHarnessError
from app.harness.node_contracts import (
    NodeConformanceReport,
    NodeConformanceResult,
    NodeContractError,
    NodeContractKit,
    NodeTimeoutError,
    TypedNodeError,
)
from app.harness.replay import build_deterministic_report

__all__ = [
    "FakeCatalogProvider", "FakeIdentityProvider", "FakeModelProvider",
    "FakePolicyProvider", "FakeSemanticRegistryProvider", "FakeWarehouseProvider",
    "GraphExecutionResult", "GraphHarness", "GraphHarnessError", "TERMINAL_NODE",
    "FaultPlan", "FaultSpec", "NodeConformanceReport", "NodeConformanceResult",
    "NodeContractError", "NodeContractKit", "NodeTimeoutError", "TypedNodeError",
    "build_deterministic_report",
]
