"""Versioned OpenSearch catalog mapping contracts.

This module only produces data structures and compares them. It deliberately
does not import an OpenSearch client or mutate aliases in an external system.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

CATALOG_INDEX_PREFIX = "imd-catalog"
EMBEDDING_DIMENSIONS = 384
EMBEDDING_SIMILARITY = "cosine"


class CatalogMappingCompatibilityError(ValueError):
    """Raised when a mapping change would invalidate an index generation."""


@dataclass(frozen=True)
class CatalogMappingVersions:
    """Versions that identify the physical catalog index contract."""

    schema_version: str = "imd-catalog-schema-v1"
    embedding_model_version: str = "imd-text-embedding-v1"
    analyzer_version: str = "imd-analyzer-v1"
    generation: str = "1"
    embedding_dimensions: int = EMBEDDING_DIMENSIONS
    embedding_similarity: str = EMBEDDING_SIMILARITY

    def __post_init__(self) -> None:
        for name in (
            "schema_version",
            "embedding_model_version",
            "analyzer_version",
            "generation",
            "embedding_similarity",
        ):
            if not getattr(self, name).strip():
                raise ValueError(f"{name} must be non-empty")
        if self.embedding_dimensions <= 0:
            raise ValueError("embedding_dimensions must be positive")

    @property
    def index_name(self) -> str:
        return (
            f"{CATALOG_INDEX_PREFIX}-{self.schema_version}-"
            f"{self.embedding_model_version}-{self.generation}"
        )


def generate_catalog_mapping(
    versions: CatalogMappingVersions | None = None,
) -> dict[str, Any]:
    """Return a deterministic mapping, settings, metadata, and alias model."""
    versions = versions or CatalogMappingVersions()
    return {
        "settings": {
            "index": {
                "knn": True,
                "knn.algo_param.ef_search": 64,
                "number_of_shards": 1,
                "number_of_replicas": 0,
            },
            "analysis": {
                "analyzer": {
                    "imd_catalog_text": {
                        "type": "custom",
                        "tokenizer": "standard",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
        "mappings": {
            "dynamic": "strict",
            "properties": _properties(versions),
        },
        "_meta": {
            "schema_version": versions.schema_version,
            "embedding_model_version": versions.embedding_model_version,
            "embedding_dimensions": versions.embedding_dimensions,
            "embedding_similarity": versions.embedding_similarity,
            "analyzer_version": versions.analyzer_version,
            "generation": versions.generation,
        },
        "aliases": {
            f"{CATALOG_INDEX_PREFIX}-read": {"is_write_index": False},
            f"{CATALOG_INDEX_PREFIX}-write": {"is_write_index": True},
        },
    }


def compatibility_errors(
    previous: Mapping[str, Any], current: Mapping[str, Any]
) -> tuple[str, ...]:
    """Return stable explanations for changes requiring a new contract."""
    errors: list[str] = []
    previous_meta = previous.get("_meta", {})
    current_meta = current.get("_meta", {})
    for field in (
        "schema_version",
        "embedding_model_version",
        "embedding_dimensions",
        "embedding_similarity",
        "analyzer_version",
    ):
        if previous_meta.get(field) != current_meta.get(field):
            errors.append(f"metadata.{field} changed")

    previous_properties = previous.get("mappings", {}).get("properties", {})
    current_properties = current.get("mappings", {}).get("properties", {})
    for field in _REQUIRED_FIELDS:
        if field not in previous_properties or field not in current_properties:
            errors.append(f"required field {field} is missing")
            continue
        old_type = _field_type(previous_properties[field])
        new_type = _field_type(current_properties[field])
        if old_type != new_type:
            errors.append(f"field {field} type changed from {old_type} to {new_type}")

    if previous_properties.get("embedding", {}).get("dimension") != current_properties.get(
        "embedding", {}
    ).get("dimension"):
        errors.append("embedding.dimension changed")
    if previous_properties.get("embedding", {}).get("method", {}).get(
        "space_type"
    ) != current_properties.get("embedding", {}).get("method", {}).get("space_type"):
        errors.append("embedding similarity changed")
    if previous.get("settings", {}).get("analysis") != current.get("settings", {}).get("analysis"):
        errors.append("settings.analysis changed")
    if not current_meta.get("generation"):
        errors.append("metadata.generation is missing")
    return tuple(errors)


def is_compatible_mapping(previous: Mapping[str, Any], current: Mapping[str, Any]) -> bool:
    """Return whether two mappings can share the same indexed contract."""
    return not compatibility_errors(previous, current)


def _field_type(field: Mapping[str, Any]) -> str:
    return str(field.get("type", "object"))


def _properties(versions: CatalogMappingVersions) -> dict[str, Any]:
    keyword = {"type": "keyword"}
    return {
        "experience_id": keyword,
        "experience_id_normalized": keyword,
        "creator_id": keyword,
        "tenant_id": keyword,
        "title": _text_field(),
        "description": _text_field(),
        "tags": {"type": "keyword"},
        "genres": {"type": "keyword"},
        "themes": {"type": "keyword"},
        "mechanics": {"type": "keyword"},
        "locales": {"type": "keyword"},
        "devices": {"type": "keyword"},
        "age_rating": keyword,
        "safety_state": keyword,
        "availability": keyword,
        "blocked": {"type": "boolean"},
        "source_type": keyword,
        "source_id": keyword,
        "provenance_ref": keyword,
        "content_version": keyword,
        "permission_version": keyword,
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
        "freshness_band": keyword,
        "quality_band": keyword,
        "popularity_band": keyword,
        "signals_version": keyword,
        "modality": keyword,
        "exposure_key": keyword,
        "synthetic": {"type": "boolean"},
        "embedding": {
            "type": "knn_vector",
            "dimension": versions.embedding_dimensions,
            "method": {
                "name": "hnsw",
                "space_type": versions.embedding_similarity,
                "engine": "lucene",
                "parameters": {"ef_construction": 128, "m": 16},
            },
        },
    }


def _text_field() -> dict[str, Any]:
    return {"type": "text", "analyzer": "imd_catalog_text", "fields": {"keyword": {"type": "keyword"}}}


_REQUIRED_FIELDS = frozenset(
    {
        "experience_id",
        "creator_id",
        "tenant_id",
        "title",
        "description",
        "tags",
        "genres",
        "themes",
        "locales",
        "devices",
        "age_rating",
        "safety_state",
        "availability",
        "blocked",
        "source_type",
        "source_id",
        "provenance_ref",
        "content_version",
        "permission_version",
        "freshness_band",
        "embedding",
    }
)
