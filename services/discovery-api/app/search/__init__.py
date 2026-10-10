"""Provider-neutral search contracts for immersive discovery."""

from .mapping import (
    CatalogMappingCompatibilityError,
    CatalogMappingVersions,
    compatibility_errors,
    generate_catalog_mapping,
    is_compatible_mapping,
)

__all__ = [
    "CatalogMappingCompatibilityError",
    "CatalogMappingVersions",
    "compatibility_errors",
    "generate_catalog_mapping",
    "is_compatible_mapping",
]
