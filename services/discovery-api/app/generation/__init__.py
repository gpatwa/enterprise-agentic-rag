"""Deterministic synthetic data generation for immersive discovery."""

from .catalog import (
    CatalogDataset,
    CatalogManifest,
    CatalogProfile,
    CatalogProfileSpec,
    generate_catalog,
    profile_spec,
)

__all__ = [
    "CatalogDataset",
    "CatalogManifest",
    "CatalogProfile",
    "CatalogProfileSpec",
    "generate_catalog",
    "profile_spec",
]
