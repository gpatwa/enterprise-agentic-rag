import pytest
from pydantic import ValidationError

from packages.platform_contracts.tool_registry import (
    IncompatibleContractError,
    RetryPolicy,
    RiskClass,
    ToolRegistry,
    ToolRegistryError,
    ToolSpec,
    UnsupportedToolVersionError,
)


def spec(**overrides: object) -> ToolSpec:
    values = {
        "tool_id": "catalog.lookup",
        "version": "v1",
        "capability": "catalog.read",
        "risk_class": RiskClass.READ,
        "timeout_ms": 2_000,
        "retry_policy": RetryPolicy(max_attempts=2, backoff_ms=100),
        "idempotency_mode": "none",
        "input_contract_version": "v1",
        "output_contract_version": "v1",
        "required_scope": "tenant_and_purpose",
        "allowed_purposes": ("analytics",),
    }
    values.update(overrides)
    return ToolSpec(**values)


def test_register_and_lookup_returns_metadata_only() -> None:
    registry = ToolRegistry()
    registry.register(spec())
    result = registry.lookup(
        "catalog.lookup", "v1", input_contract_version="v1", output_contract_version="v1",
        tenant_id="tenant-a", purpose="analytics",
    )
    assert result.tool_id == "catalog.lookup"
    assert not hasattr(result, "execute")


def test_undeclared_and_unsupported_version_fail_closed() -> None:
    registry = ToolRegistry((spec(),))
    with pytest.raises(UnsupportedToolVersionError):
        registry.lookup("missing", "v1", input_contract_version="v1", output_contract_version="v1")
    with pytest.raises(UnsupportedToolVersionError):
        registry.lookup("catalog.lookup", "v2", input_contract_version="v1", output_contract_version="v1")


def test_duplicate_identity_fails_closed() -> None:
    registry = ToolRegistry((spec(),))
    with pytest.raises(ToolRegistryError, match="duplicate"):
        registry.register(spec())


def test_incompatible_contracts_fail_closed() -> None:
    registry = ToolRegistry((spec(),))
    with pytest.raises(IncompatibleContractError):
        registry.lookup("catalog.lookup", "v1", input_contract_version="v2", output_contract_version="v1")


@pytest.mark.parametrize(
    "overrides",
    [
        {"risk_class": "unknown"},
        {"timeout_ms": 0},
        {"timeout_ms": 300_001},
        {"idempotency_mode": "required"},
        {"idempotency_mode": "optional", "idempotency_key_required": True},
    ],
)
def test_invalid_metadata_fails_closed(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        spec(**overrides)


@pytest.mark.parametrize("capability", ["raw_sql", "execute_sql", "authorize_policy", "tool_execution"])
def test_unsafe_capability_fails_closed(capability: str) -> None:
    with pytest.raises(ToolRegistryError, match="unsafe capability"):
        ToolRegistry((spec(capability=capability),))


def test_destructive_tool_requires_both_scopes() -> None:
    with pytest.raises(ValidationError, match="tenant_and_purpose"):
        spec(risk_class=RiskClass.DESTRUCTIVE, required_scope="tenant")


def test_purpose_scope_requires_allowlist_and_rejects_other_purposes() -> None:
    with pytest.raises(ValidationError, match="allowed_purposes"):
        spec(allowed_purposes=())
    registry = ToolRegistry((spec(),))
    with pytest.raises(ToolRegistryError, match="purpose is not allowed"):
        registry.lookup(
            "catalog.lookup", "v1", input_contract_version="v1", output_contract_version="v1",
            tenant_id="tenant-a", purpose="billing",
        )


def test_registry_allowlist_rejects_sql_and_execution_aliases() -> None:
    for capability in ("sql", "execute", "shell.command", "policy.authorize"):
        with pytest.raises(ToolRegistryError, match="unsafe capability"):
            ToolRegistry((spec(capability=capability),))
