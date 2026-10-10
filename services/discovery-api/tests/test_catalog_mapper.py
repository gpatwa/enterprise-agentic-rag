import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import ExperienceRecord
from app.search.mapper import CatalogDocumentInput, map_catalog_document

FIXTURE = Path(__file__).parent / "fixtures" / "golden" / "experiences.json"


def _source(**overrides):
    record = ExperienceRecord.model_validate(json.loads(FIXTURE.read_text())[0])
    values = {
        "record": record,
        "tenant_id": record.tenant_id,
        "source_type": "catalog-fixture",
        "source_id": record.experience_id,
        "provenance_ref": "fixture://imd-002/exp-001",
        "content_version": "content-v1",
        "permission_version": "permission-v1",
        "embedding": tuple(0.01 for _ in range(384)),
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 2, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return CatalogDocumentInput(**values)


def test_maps_golden_record_with_required_metadata_and_approved_signals():
    document = map_catalog_document(_source())

    assert document.experience_id == "exp-001"
    assert document.experience_id_normalized == "exp-001"
    assert document.tags == (
        "adventure",
        "coastal",
        "cooperative-puzzle",
        "exploration",
        "mystery",
        "puzzle",
    )
    assert document.content_version == "content-v1"
    assert document.permission_version == "permission-v1"
    assert document.signals_version == "v1"
    assert document.exposure_key == map_catalog_document(_source()).exposure_key
    assert len(document.embedding) == 384


def test_serialization_is_stable_and_has_deterministic_document_id():
    first = map_catalog_document(_source())
    second = map_catalog_document(_source())

    assert first.stable_json() == second.stable_json()
    assert first.stable_json().startswith('{"age_rating":')
    assert first.exposure_key == "0b4850c635938af68caffde2400687435f1a6be962aaa2d9e25faad1c6b03d55"


@pytest.mark.parametrize(
    "field,value",
    [
        ("provenance_ref", ""),
        ("content_version", ""),
        ("permission_version", ""),
        ("tenant_id", "tenant-other"),
        ("embedding", tuple(0.01 for _ in range(383))),
    ],
)
def test_rejects_missing_or_incompatible_metadata(field, value):
    with pytest.raises(ValidationError):
        _source(**{field: value})


def test_rejects_blocked_and_unavailable_records():
    with pytest.raises(ValidationError):
        _source(blocked=True)

    record = json.loads(FIXTURE.read_text())[0] | {"availability": "unavailable"}
    with pytest.raises(ValueError, match="blocked or unavailable"):
        map_catalog_document(_source(record=ExperienceRecord.model_validate(record)))


def test_prohibited_user_fields_are_not_accepted_or_emitted():
    document = map_catalog_document(_source())
    assert "user_id" not in document.model_dump()
    assert "history" not in document.model_dump()
    with pytest.raises(ValidationError):
        CatalogDocumentInput(**{**_source().model_dump(), "user_id": "user-001"})
