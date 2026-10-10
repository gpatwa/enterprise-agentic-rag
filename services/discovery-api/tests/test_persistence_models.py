from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import ConsentState
from app.events.models import EventType
from app.persistence.models import (
    CatalogPersistenceRecord,
    DerivedVersionMetadata,
    InteractionEventRecord,
    ProfilePersistenceRecord,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_persistence_models_round_trip_with_versions_and_derived_metadata() -> None:
    catalog = CatalogPersistenceRecord(
        tenant_id="tenant-a",
        experience_id="experience-1",
        creator_id="creator-1",
        record_version="v1",
        content_version="content-1",
        permission_version="permissions-1",
        source_type="fixture",
        source_id="fixture-1",
        provenance_ref="fixture://catalog/1",
        synthetic=True,
        created_at=NOW,
        updated_at=NOW,
        authoritative_payload={"title": "Sky Circuit", "tags": ["racing"]},
    )
    profile = ProfilePersistenceRecord(
        tenant_id="tenant-a",
        user_id="user-1",
        profile_version="v1",
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        synthetic=True,
        created_at=NOW,
        updated_at=NOW,
        profile_payload={"locale": "en-US"},
    )
    derived = DerivedVersionMetadata(
        tenant_id="tenant-a",
        subject_type="experience",
        subject_id="experience-1",
        derived_kind="embedding",
        derived_version="embedding-v1",
        source_version="content-1",
        generated_at=NOW,
        metadata={"model": "imd-text-embedding-v1"},
    )

    assert CatalogPersistenceRecord.model_validate(catalog.model_dump()) == catalog
    assert ProfilePersistenceRecord.model_validate(profile.model_dump()) == profile
    assert DerivedVersionMetadata.model_validate(derived.model_dump()) == derived


def test_tenant_scoped_identity_and_event_idempotency_are_explicit() -> None:
    first = InteractionEventRecord(
        tenant_id="tenant-a",
        event_id="event-1",
        idempotency_key="request-1:click:experience-1",
        event_version="v1",
        event_type=EventType.CLICK,
        user_id="user-1",
        experience_id="experience-1",
        request_id="request-1",
        occurred_at=NOW,
        received_at=NOW,
        consent_state=ConsentState.PERSONALIZATION_ALLOWED,
        synthetic=True,
        event_payload={"target": "card"},
    )
    second_tenant = first.model_copy(
        update={"tenant_id": "tenant-b", "event_id": "event-1", "idempotency_key": first.idempotency_key}
    )

    assert first.event_id == second_tenant.event_id
    assert first.tenant_id != second_tenant.tenant_id
    assert first.idempotency_key == second_tenant.idempotency_key


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("created_at", datetime(2026, 1, 1), "timezone-aware"),
        ("record_version", "", "String should have at least 1 character"),
    ],
)
def test_versions_and_timestamps_are_required(field: str, value: object, message: str) -> None:
    values = {
        "tenant_id": "tenant-a",
        "experience_id": "experience-1",
        "creator_id": "creator-1",
        "record_version": "v1",
        "content_version": "content-1",
        "permission_version": "permissions-1",
        "source_type": "fixture",
        "source_id": "fixture-1",
        "provenance_ref": "fixture://catalog/1",
        "synthetic": True,
        "created_at": NOW,
        "updated_at": NOW,
        "authoritative_payload": {},
    }
    values[field] = value

    with pytest.raises(ValidationError, match=message):
        CatalogPersistenceRecord(**values)


def test_payloads_are_bounded_and_migration_is_non_destructive() -> None:
    values = {
        "tenant_id": "tenant-a",
        "experience_id": "experience-1",
        "creator_id": "creator-1",
        "record_version": "v1",
        "content_version": "content-1",
        "permission_version": "permissions-1",
        "source_type": "fixture",
        "source_id": "fixture-1",
        "provenance_ref": "fixture://catalog/1",
        "synthetic": True,
        "created_at": NOW,
        "updated_at": NOW,
        "authoritative_payload": {"blob": "x" * (64 * 1024)},
    }
    with pytest.raises(ValidationError, match="exceeds"):
        CatalogPersistenceRecord(**values)

    migration = Path(__file__).parents[1] / "app/persistence/migrations/0001_discovery_baseline.sql"
    sql = migration.read_text(encoding="utf-8")
    assert "CREATE TABLE discovery_catalog_records" in sql
    assert "CREATE TABLE discovery_profiles" in sql
    assert "CREATE TABLE discovery_interaction_events" in sql
    assert "CREATE TABLE discovery_derived_version_metadata" in sql
    assert "UNIQUE (tenant_id, idempotency_key)" in sql
    assert "DROP TABLE" not in sql.upper()
    assert "opensearch" not in sql.lower()
