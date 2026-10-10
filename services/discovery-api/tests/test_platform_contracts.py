from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from packages.platform_contracts import (
    DecisionTrace,
    DiscoveryComponentVersion,
    DiscoveryRequestContext,
    ImpressionToken,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)
COMPONENT = DiscoveryComponentVersion(
    component_type="schema",
    name="discovery-contract",
    version="v1",
    digest="a" * 64,
)


def context(**overrides) -> DiscoveryRequestContext:
    values = {
        "tenant_id": "tenant-orbit",
        "principal_id": "user-001",
        "request_id": "request-001",
        "purpose": "search",
        "locale": "en-US",
        "device": "web",
        "age": 13,
        "consent": ("personalization",),
        "groups": ("family-safe",),
        "context": (("surface", "home"),),
    }
    values.update(overrides)
    return DiscoveryRequestContext(**values)


def token_for(request_context: DiscoveryRequestContext | None = None) -> ImpressionToken:
    return ImpressionToken.for_context(
        request_context or context(),
        token_id="impression-001",
        issued_at=NOW,
        expires_at=NOW + timedelta(minutes=5),
        schema_version="catalog-v1",
        components=(COMPONENT,),
    )


def test_all_contracts_import_and_round_trip_deterministically() -> None:
    request_context = context()
    token = token_for(request_context)
    trace = DecisionTrace(
        trace_id="trace-001",
        tenant_id=request_context.tenant_id,
        principal_id=request_context.principal_id,
        request_id=request_context.request_id,
        started_at=NOW,
        completed_at=NOW + timedelta(milliseconds=12),
        stages=(
            {
                "stage": "retrieval",
                "outcome": "completed",
                "duration_ms": 12.5,
                "candidate_count": 10,
                "reason_codes": ("hybrid",),
                "components": (COMPONENT,),
            },
        ),
    )

    for model in (request_context, COMPONENT, token, trace):
        encoded = model.model_dump_json()
        assert model.model_validate_json(encoded).model_dump_json() == encoded


@pytest.mark.parametrize(
    "field,value",
    [
        ("tenant_id", ""),
        ("principal_id", " "),
        ("age", 151),
        ("duration_ms", float("nan")),
    ],
)
def test_invalid_values_are_rejected(field: str, value: object) -> None:
    if field == "duration_ms":
        with pytest.raises(ValidationError):
            DecisionTrace(
                trace_id="trace-001",
                tenant_id="tenant-orbit",
                principal_id="user-001",
                request_id="request-001",
                started_at=NOW,
                completed_at=NOW,
                stages=(
                    {
                        "stage": "retrieval",
                        "outcome": "completed",
                        "duration_ms": value,
                        "candidate_count": 1,
                    },
                ),
            )
    else:
        with pytest.raises(ValidationError):
            context(**{field: value})


def test_extra_fields_naive_timestamps_and_oversized_collections_are_rejected() -> None:
    with pytest.raises(ValidationError):
        context(unexpected="value")
    with pytest.raises(ValidationError):
        context(groups=tuple(f"group-{index}" for index in range(51)))
    token_values = token_for().model_dump()
    token_values["issued_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError):
        ImpressionToken(**token_values)


def test_models_are_frozen() -> None:
    request_context = context()
    with pytest.raises(ValidationError):
        request_context.tenant_id = "other-tenant"


def test_impression_token_is_bound_to_tenant_and_request_identity() -> None:
    token = token_for()
    token.validate_for(context())
    with pytest.raises(ValueError):
        token.validate_for(context(tenant_id="tenant-lumen"))
    with pytest.raises(ValueError):
        token.validate_for(context(request_id="request-002"))


@pytest.mark.parametrize("field", ["query", "history", "vector", "provider_payload"])
def test_trace_rejects_raw_query_history_vectors_and_provider_payloads(field: str) -> None:
    with pytest.raises(ValidationError):
        DecisionTrace(
            trace_id="trace-001",
            tenant_id="tenant-orbit",
            principal_id="user-001",
            request_id="request-001",
            started_at=NOW,
            completed_at=NOW,
            stages=(
                {
                    "stage": "retrieval",
                    "outcome": "completed",
                    "duration_ms": 1.0,
                    "candidate_count": 1,
                    field: "must-not-be-recorded",
                },
            ),
        )


def test_shared_contract_module_does_not_import_product_modules() -> None:
    import sys

    assert not any(
        name.startswith(("services.discovery", "services.analytics", "services.api"))
        for name in sys.modules
    )
