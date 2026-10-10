"""Deterministic CPU two-tower retrieval baseline.

This module is an offline contract and baseline, not a trained model.  It uses
versioned hash projections so local fixtures can produce reproducible vectors
without a neural dependency or a live model provider.
"""
from __future__ import annotations

import hashlib
import math
from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_MAX_DIMENSIONS = 4096
_MAX_ITEMS = 10_000
_ID = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$"
_TOKEN = r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$"


class Tower(str, Enum):
    USER = "user"
    ITEM = "item"


class _Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, protected_namespaces=())


class TwoTowerSpec(_Contract):
    """The immutable embedding contract shared by both towers."""

    model_version: str = Field(default="imd-two-tower-v1", min_length=1, max_length=128, pattern=_VERSION)
    dimensions: int = Field(default=32, ge=1, le=_MAX_DIMENSIONS)
    algorithm: str = Field(default="sha256_signed_projection", min_length=1, max_length=64, pattern=_VERSION)


class UserTowerInput(_Contract):
    """Privacy-conscious features used to build a user vector.

    The baseline accepts stable feature tokens rather than free-form profile
    text.  An empty token set is a supported deterministic cold start.
    """

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    user_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    feature_tokens: tuple[str, ...] = Field(default_factory=tuple, max_length=256)

    @field_validator("feature_tokens")
    @classmethod
    def validate_tokens(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not token or len(token) > 128 for token in value):
            raise ValueError("feature tokens must be non-empty and at most 128 characters")
        if len(set(value)) != len(value):
            raise ValueError("feature tokens must be unique")
        return tuple(sorted(value))


class ItemTowerInput(_Contract):
    """Catalog features used to build an item vector."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    item_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    feature_tokens: tuple[str, ...] = Field(default_factory=tuple, max_length=256)

    @field_validator("feature_tokens")
    @classmethod
    def validate_tokens(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not token or len(token) > 128 for token in value):
            raise ValueError("feature tokens must be non-empty and at most 128 characters")
        if len(set(value)) != len(value):
            raise ValueError("feature tokens must be unique")
        return tuple(sorted(value))


class TowerVector(_Contract):
    """A versioned, finite, normalized vector with no raw feature payload."""

    tenant_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    subject_id: str = Field(min_length=1, max_length=255, pattern=_ID)
    tower: Tower
    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    dimensions: int = Field(ge=1, le=_MAX_DIMENSIONS)
    values: tuple[float, ...] = Field(min_length=1, max_length=_MAX_DIMENSIONS)
    cold_start: bool

    @field_validator("values")
    @classmethod
    def validate_values(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(item) for item in value):
            raise ValueError("vector values must be finite")
        return tuple(float(item) for item in value)

    @model_validator(mode="after")
    def validate_dimensions(self) -> "TowerVector":
        if len(self.values) != self.dimensions:
            raise ValueError("vector dimensions do not match values")
        norm = math.sqrt(sum(value * value for value in self.values))
        if not math.isfinite(norm) or norm == 0:
            raise ValueError("vector must be finite and non-zero")
        return self


class AnnExport(_Contract):
    """Reproducible offline item-vector export receipt."""

    model_version: str = Field(min_length=1, max_length=128, pattern=_VERSION)
    dimensions: int = Field(ge=1, le=_MAX_DIMENSIONS)
    vectors: tuple[TowerVector, ...] = Field(max_length=_MAX_ITEMS)
    checksum: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_export(self) -> "AnnExport":
        if any(vector.tower is not Tower.ITEM for vector in self.vectors):
            raise ValueError("ANN exports accept item vectors only")
        if any(vector.model_version != self.model_version or vector.dimensions != self.dimensions for vector in self.vectors):
            raise ValueError("export vectors must match the export contract")
        ids = [(vector.tenant_id, vector.subject_id) for vector in self.vectors]
        if len(ids) != len(set(ids)):
            raise ValueError("export vector identities must be unique")
        if self.checksum != _export_checksum(self.vectors):
            raise ValueError("export checksum does not match vectors")
        return self


class TwoTowerBaseline:
    """Build reproducible user/item vectors with a hash-projection baseline."""

    def __init__(self, spec: TwoTowerSpec | None = None) -> None:
        self.spec = spec or TwoTowerSpec()

    def user_vector(self, value: UserTowerInput) -> TowerVector:
        return self._vector(Tower.USER, value.tenant_id, value.user_id, value.feature_tokens)

    def item_vector(self, value: ItemTowerInput) -> TowerVector:
        return self._vector(Tower.ITEM, value.tenant_id, value.item_id, value.feature_tokens)

    def export_items(self, values: Iterable[ItemTowerInput]) -> AnnExport:
        items = tuple(values)
        if len(items) > _MAX_ITEMS:
            raise ValueError(f"items cannot exceed {_MAX_ITEMS} records")
        vectors = tuple(sorted((self.item_vector(item) for item in items), key=lambda item: (item.tenant_id, item.subject_id)))
        return AnnExport(
            model_version=self.spec.model_version,
            dimensions=self.spec.dimensions,
            vectors=vectors,
            checksum=_export_checksum(vectors),
        )

    def _vector(self, tower: Tower, tenant_id: str, subject_id: str, tokens: tuple[str, ...]) -> TowerVector:
        # Include the identity in the empty-token case so every cold-start
        # subject receives a stable, non-zero vector without exposing features.
        inputs = tokens or (f"cold_start:{subject_id}",)
        values = [0.0] * self.spec.dimensions
        for token in inputs:
            digest = hashlib.sha256(
                f"{self.spec.model_version}|{tower.value}|{tenant_id}|{token}".encode("utf-8")
            ).digest()
            for index in range(self.spec.dimensions):
                offset = (index * 2) % len(digest)
                bucket = int.from_bytes(digest[offset : offset + 2], "big")
                values[index] += 1.0 if bucket % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in values))
        normalized = tuple(round(value / norm, 12) for value in values)
        return TowerVector(
            tenant_id=tenant_id,
            subject_id=subject_id,
            tower=tower,
            model_version=self.spec.model_version,
            dimensions=self.spec.dimensions,
            values=normalized,
            cold_start=not tokens,
        )


def _export_checksum(vectors: tuple[TowerVector, ...]) -> str:
    payload = "\n".join(
        f"{item.tenant_id}|{item.subject_id}|{item.model_version}|{item.dimensions}|"
        + ",".join(f"{value:.12f}" for value in item.values)
        for item in vectors
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
