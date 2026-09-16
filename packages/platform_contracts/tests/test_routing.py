from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from pydantic import ValidationError

from packages.platform_contracts.routing import (
    RouteDecision,
    RoutingConfig,
    RoutingContext,
    RoutingRefusal,
    RoutingTransitionError,
    TrustedAuthorizationArtifact,
    require_governed_action,
    resolve_route,
    validate_mode_transition,
)


def context(**changes: Any) -> RoutingContext:
    values: dict[str, Any] = {
        "tenant_id": "tenant-a",
        "request_id": "request-1",
        "purpose": "analytics",
    }
    values.update(changes)
    return RoutingContext(**values)


def test_default_is_legacy_and_unknown_mode_fails_closed() -> None:
    decision = resolve_route(RoutingConfig(), context())
    assert decision.mode == "legacy"
    assert decision.execute_legacy is True
    with pytest.raises(ValidationError):
        RoutingConfig(default_mode="unknown")


@pytest.mark.parametrize(
    ("mode", "legacy", "governed", "shadow"),
    [("legacy", True, False, False), ("shadow", True, False, True)],
)
def test_legacy_and_shadow_preserve_legacy_result(mode: str, legacy: bool, governed: bool, shadow: bool) -> None:
    decision = resolve_route(RoutingConfig(default_mode=mode), context())
    assert (decision.execute_legacy, decision.execute_governed, decision.record_shadow) == (legacy, governed, shadow)


def test_shadow_cannot_execute_governed_action() -> None:
    decision = resolve_route(RoutingConfig(default_mode="shadow"), context())
    with pytest.raises(RoutingRefusal, match="shadow"):
        require_governed_action(decision)


def test_disabled_refuses_clearly_and_cannot_execute_action() -> None:
    decision = resolve_route(RoutingConfig(default_mode="disabled"), context())
    assert decision.refusal_reason == "routing is disabled for this tenant"
    with pytest.raises(RoutingRefusal, match="disabled"):
        require_governed_action(decision)


def test_governed_requires_explicit_rollout_approval_and_audit_context() -> None:
    with pytest.raises(RoutingRefusal, match="trusted authorization"):
        resolve_route(RoutingConfig(default_mode="governed"), context())
    issued = datetime.now(timezone.utc)
    artifact = TrustedAuthorizationArtifact.issue(
        artifact_id="artifact-1", tenant_id="tenant-a", request_id="request-1", purpose="analytics",
        rollout_id="rollout-1", approval_reference="approval-1", audit_event_id="audit-1",
        signing_key="test-key", issued_at=issued, expires_at=issued + timedelta(minutes=5),
    )
    governed = context(
        rollout_id="rollout-1",
        governed_enabled=True,
        approval_reference="approval-1",
        audit_event_id="audit-1",
        authorization_artifact=artifact,
    )
    decision = resolve_route(RoutingConfig(default_mode="governed"), governed, authorization_key="test-key")
    assert decision.execute_governed is True
    assert decision.audit_event_id == "audit-1"
    require_governed_action(decision)


def test_governed_route_rejects_tampered_or_mismatched_artifact() -> None:
    issued = datetime.now(timezone.utc)
    artifact = TrustedAuthorizationArtifact.issue(
        artifact_id="artifact-1", tenant_id="tenant-a", request_id="request-1", purpose="analytics",
        rollout_id="rollout-1", approval_reference="approval-1", audit_event_id="audit-1",
        signing_key="test-key", issued_at=issued, expires_at=issued + timedelta(minutes=5),
    )
    with pytest.raises(RoutingRefusal, match="invalid or mismatched"):
            resolve_route(
                RoutingConfig(default_mode="governed"),
            context(
                governed_enabled=True, rollout_id="rollout-1", approval_reference="approval-1",
                audit_event_id="audit-1", authorization_artifact=artifact,
            ),
            authorization_key="wrong-key",
        )
    with pytest.raises(RoutingRefusal, match="invalid or mismatched"):
        resolve_route(
            RoutingConfig(default_mode="governed"),
            context(
                governed_enabled=True, rollout_id="rollout-1", approval_reference="approval-1",
                audit_event_id="audit-1", authorization_artifact=artifact, purpose="billing",
            ),
            authorization_key="test-key",
        )


@pytest.mark.parametrize("field", ["rollout_id", "approval_reference", "audit_event_id"])
def test_governed_enablement_requires_all_context_fields(field: str) -> None:
    values = {
        "rollout_id": "rollout-1",
        "governed_enabled": True,
        "approval_reference": "approval-1",
        "audit_event_id": "audit-1",
    }
    values[field] = None
    with pytest.raises(ValidationError, match="governed enablement"):
        context(**values)


def test_rollout_selection_is_tenant_scoped() -> None:
    config = RoutingConfig(tenant_modes={"tenant-a": "shadow", "tenant-b": "disabled"})
    assert resolve_route(config, context(tenant_id="tenant-a")).mode == "shadow"
    assert resolve_route(config, context(tenant_id="tenant-b")).mode == "disabled"
    assert resolve_route(config, context(tenant_id="tenant-c")).mode == "legacy"


def test_decision_cannot_forge_governed_capabilities() -> None:
    with pytest.raises(ValidationError, match="capabilities"):
        RouteDecision(
            tenant_id="tenant-a",
            request_id="request-1",
            mode="shadow",
            execute_legacy=True,
            execute_governed=True,
            record_shadow=True,
        )


def test_disabled_cannot_jump_directly_to_governed() -> None:
    with pytest.raises(RoutingTransitionError, match="invalid routing transition"):
        validate_mode_transition("disabled", "governed")
    assert validate_mode_transition("shadow", "governed") == "governed"
