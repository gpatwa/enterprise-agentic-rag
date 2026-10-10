from datetime import datetime, timezone

import pytest

from app.domain.models import ConsentState
from app.experiments.assignment import (
    AssignmentRejection,
    ExperimentAssigner,
    ExperimentConfig,
    ExperimentVariant,
)
from packages.platform_contracts.discovery import DiscoveryComponentVersion

UTC = timezone.utc
EXPOSED_AT = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def config(**changes: object) -> ExperimentConfig:
    values: dict[str, object] = {
        "experiment_id": "ranking-v2",
        "assignment_version": "v1",
        "variants": (ExperimentVariant(name="control"), ExperimentVariant(name="treatment")),
        "allowed_tenants": ("tenant-orbit",),
        "component_versions": (
            DiscoveryComponentVersion(
                component_type="model", name="ranker", version="model-v1", digest="a" * 64
            ),
        ),
    }
    values.update(changes)
    return ExperimentConfig(**values)


def test_assignment_is_stable_and_redacts_identity() -> None:
    assigner = ExperimentAssigner()
    first = assigner.assign(config(), tenant_id="tenant-orbit", user_id="user-001")
    second = assigner.assign(config(), tenant_id="tenant-orbit", user_id="user-001")
    assert first == second
    assert first.variant in {"control", "treatment"}
    assert "tenant-orbit" not in first.model_dump_json()
    assert "user-001" not in first.model_dump_json()


def test_exposure_is_immutable_idempotent_and_contains_versions_only() -> None:
    assigner = ExperimentAssigner()
    assignment = assigner.assign(config(), tenant_id="tenant-orbit", user_id="user-001")
    first = assigner.expose(assignment, exposed_at=EXPOSED_AT)
    replay = assigner.expose(assignment, exposed_at=EXPOSED_AT)
    assert first == replay
    assert len(assigner.exposures) == 1
    assert first.component_versions[0].version == "model-v1"
    assert "user-001" not in first.model_dump_json()
    assert "query" not in first.model_dump_json()


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"allowlisted": False}, AssignmentRejection.NOT_ALLOWLISTED),
        ({"allowed_tenants": ("tenant-other",)}, AssignmentRejection.TENANT_NOT_ALLOWED),
    ],
)
def test_allowlist_and_tenant_scope_fail_closed(changes: dict[str, object], reason: AssignmentRejection) -> None:
    assigner = ExperimentAssigner()
    with pytest.raises(ValueError, match=reason.value):
        assigner.assign(config(**changes), tenant_id="tenant-orbit", user_id="user-001")


def test_consent_is_required_and_variants_are_unique() -> None:
    assigner = ExperimentAssigner()
    with pytest.raises(ValueError, match=AssignmentRejection.CONSENT_REQUIRED.value):
        assigner.assign(
            config(),
            tenant_id="tenant-orbit",
            user_id="user-001",
            consent_state=ConsentState.PERSONALIZATION_DENIED,
        )
    with pytest.raises(ValueError, match="mutually exclusive"):
        config(variants=(ExperimentVariant(name="control"), ExperimentVariant(name="control")))


def test_assignment_version_changes_bucket_contract() -> None:
    assigner = ExperimentAssigner()
    first = assigner.assign(config(assignment_version="v1"), tenant_id="tenant-orbit", user_id="user-001")
    second = assigner.assign(config(assignment_version="v2"), tenant_id="tenant-orbit", user_id="user-001")
    assert first.assignment_version != second.assignment_version
    assert first.experiment_digest != second.experiment_digest
