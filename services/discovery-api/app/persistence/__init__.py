"""Authoritative persistence contracts for immersive discovery."""

from app.persistence.models import (
    CatalogPersistenceRecord,
    DerivedVersionMetadata,
    InteractionEventRecord,
    ProfilePersistenceRecord,
)

__all__ = [
    "CatalogPersistenceRecord",
    "DerivedVersionMetadata",
    "InteractionEventRecord",
    "ProfilePersistenceRecord",
]
