"""Fictional demo catalog for the local and pilot Discovery service.

Everything here is generated from a fixed seed: fictional experiences and synthetic users, no
customer data and no third-party catalog. It is demonstration data, not evidence of real engagement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import ExperienceRecord, UserProfile
from app.generation.catalog import CatalogProfile, generate_catalog
from app.search.mapper import (
    CatalogDocumentInput,
    CatalogDocumentMappingError,
    CatalogSearchDocument,
    map_catalog_document,
)

DEMO_SEED = 7
_EMBEDDING_DIMENSIONS = 384
_FIXED_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_demo_catalog(
    seed: int = DEMO_SEED,
) -> tuple[tuple[ExperienceRecord, ...], tuple[CatalogSearchDocument, ...], tuple[UserProfile, ...]]:
    """Return experiences, lexical search documents and synthetic users for a seed (deterministic)."""
    dataset = generate_catalog(seed, CatalogProfile.DEMO)
    documents: list[CatalogSearchDocument] = []
    for record in dataset.experiences:
        source = CatalogDocumentInput(
            record=record,
            tenant_id=record.tenant_id,
            source_type="generated",
            source_id=record.experience_id,
            provenance_ref=f"generated://seed-{seed}/{record.experience_id}",
            content_version="v1",
            permission_version="v1",
            # Lexical search only: vectors are off by default, so a constant embedding is inert.
            embedding=tuple(0.01 for _ in range(_EMBEDDING_DIMENSIONS)),
            created_at=_FIXED_TIME,
            updated_at=_FIXED_TIME,
        )
        try:
            documents.append(map_catalog_document(source))
        except CatalogDocumentMappingError:
            # The generator deliberately includes blocked or unavailable experiences; they are not searchable.
            continue
    return dataset.experiences, tuple(documents), dataset.users
