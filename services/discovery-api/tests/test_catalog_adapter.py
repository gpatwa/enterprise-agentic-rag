from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.adapters.catalog import (
    CatalogAdapterRecord,
    CatalogProvenance,
    FixtureCatalogAdapter,
    ProvenanceError,
    SourceType,
)
from app.domain.models import ExperienceRecord


def _experience(experience_id: str, tenant_id: str = "tenant-orbit", *, synthetic: bool = True) -> ExperienceRecord:
    return ExperienceRecord(
        experience_id=experience_id,
        creator_id="creator-01",
        tenant_id=tenant_id,
        title=f"Experience {experience_id}",
        description="A bounded synthetic fixture experience.",
        genres=("adventure",),
        themes=("forest",),
        mechanics=("exploration",),
        devices=("desktop",),
        locales=("en-US",),
        age_rating="E",
        safety_state="approved",
        availability="available",
        synthetic=synthetic,
        provenance="synthetic" if synthetic else "licensed",
    )


def _record(
    experience_id: str,
    tenant_id: str = "tenant-orbit",
    *,
    synthetic: bool = True,
    source_type: SourceType = SourceType.FIXTURE,
    provenance_ref: str = "fixture://catalog/v1",
) -> CatalogAdapterRecord:
    return CatalogAdapterRecord(
        experience=_experience(experience_id, tenant_id, synthetic=synthetic),
        provenance=CatalogProvenance(
            source_type=source_type,
            source_id=f"fixture-{experience_id}",
            tenant_id=tenant_id,
            provenance_ref=provenance_ref,
            retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            content_version="catalog-v1",
            synthetic=synthetic,
        ),
    )


def test_valid_fixture_reads_preserve_metadata_and_order() -> None:
    adapter = FixtureCatalogAdapter((_record("exp-002"), _record("exp-001")))

    results = adapter.list_experiences("tenant-orbit")

    assert [item.experience.experience_id for item in results] == ["exp-001", "exp-002"]
    assert results[0].provenance.source_id == "fixture-exp-001"
    assert results[0].provenance.content_version == "catalog-v1"


def test_unknown_provenance_and_non_fixture_source_fail_closed() -> None:
    with pytest.raises((ProvenanceError, ValidationError)):
        _record("exp-001", provenance_ref="unknown")
    with pytest.raises((ProvenanceError, ValidationError)):
        FixtureCatalogAdapter((_record("exp-001", source_type=SourceType.LICENSED),))


def test_non_synthetic_fixture_is_rejected_by_default() -> None:
    with pytest.raises(ProvenanceError):
        FixtureCatalogAdapter((_record("exp-001", synthetic=False),))


def test_tenant_scope_and_bounded_limits() -> None:
    adapter = FixtureCatalogAdapter((_record("exp-001"), _record("exp-002", "tenant-lumen")))

    assert adapter.get_experience("tenant-orbit", "exp-002") is None
    assert adapter.list_experiences("tenant-orbit", limit=1)[0].experience.experience_id == "exp-001"
    with pytest.raises(ValueError):
        adapter.list_experiences("tenant-orbit", limit=0)


def test_mismatched_provenance_tenant_is_rejected() -> None:
    with pytest.raises((ProvenanceError, ValidationError)):
        CatalogAdapterRecord(
            experience=_experience("exp-001", "tenant-orbit"),
            provenance=CatalogProvenance(
                source_type=SourceType.FIXTURE,
                source_id="fixture-exp-001",
                tenant_id="tenant-lumen",
                provenance_ref="fixture://catalog/v1",
                retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                content_version="catalog-v1",
                synthetic=True,
            ),
        )


def test_provenance_requires_timezone_aware_retrieval() -> None:
    with pytest.raises((ProvenanceError, ValidationError)):
        CatalogProvenance(
            source_type=SourceType.FIXTURE,
            source_id="fixture-exp-001",
            tenant_id="tenant-orbit",
            provenance_ref="fixture://catalog/v1",
            retrieved_at=datetime(2026, 1, 1),
            content_version="catalog-v1",
            synthetic=True,
        )
