"""Fictional demo catalog for the local and pilot Discovery service.

Embeddings come from the local hashing embedder (word overlap, not semantics); see app/embedding.

Everything here is generated from a fixed seed: fictional experiences and synthetic users, no
customer data and no third-party catalog. It is demonstration data, not evidence of real engagement.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.domain.models import ExperienceRecord, UserProfile
from app.embedding import HASH_EMBEDDING_VERSION, HashingEmbedder
from app.generation.catalog import CatalogProfile, generate_catalog
from app.search.mapper import (
    CatalogDocumentInput,
    CatalogDocumentMappingError,
    CatalogSearchDocument,
    map_catalog_document,
)
from app.search.mapping import CatalogMappingVersions

DEMO_SEED = 7
_EMBEDDING_DIMENSIONS = 384
_FIXED_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def load_demo_catalog(
    seed: int = DEMO_SEED,
) -> tuple[tuple[ExperienceRecord, ...], tuple[CatalogSearchDocument, ...], tuple[UserProfile, ...]]:
    """Return experiences, lexical search documents and synthetic users for a seed (deterministic)."""
    dataset = generate_catalog(seed, CatalogProfile.DEMO)
    embedder = HashingEmbedder(_EMBEDDING_DIMENSIONS)
    versions = CatalogMappingVersions(embedding_model_version=HASH_EMBEDDING_VERSION)
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
            embedding=embedder.embed_document(
                record.title,
                record.description,
                tuple(sorted({str(getattr(v, "value", v)) for v in (*record.genres, *record.themes, *record.mechanics)})),
            ),
            mapping_versions=versions,
            created_at=_FIXED_TIME,
            updated_at=_FIXED_TIME,
        )
        try:
            documents.append(map_catalog_document(source))
        except CatalogDocumentMappingError:
            # The generator deliberately includes blocked or unavailable experiences; they are not searchable.
            continue
    return dataset.experiences, tuple(documents), dataset.users
