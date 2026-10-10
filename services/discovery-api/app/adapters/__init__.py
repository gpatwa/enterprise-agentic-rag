"""Provider-neutral adapters for authoritative discovery data."""

from app.adapters.catalog import (
    CatalogAdapter,
    CatalogAdapterRecord,
    CatalogProvenance,
    FixtureCatalogAdapter,
    ProvenanceError,
    SourceType,
)

__all__ = [
    "CatalogAdapter",
    "CatalogAdapterRecord",
    "CatalogProvenance",
    "FixtureCatalogAdapter",
    "ProvenanceError",
    "SourceType",
]
