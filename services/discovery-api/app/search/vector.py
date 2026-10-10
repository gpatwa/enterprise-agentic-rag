"""Deterministic, provider-neutral vector retrieval for catalog documents."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.candidates.contracts import Candidate, CandidateSourceResult, Degradation
from app.domain.models import (
    AgeRating,
    Availability,
    CatalogDevice,
    ExperienceRecord,
    Genre,
    ImmersiveDiscoveryContext,
    Locale,
    Mechanic,
    SafetyState,
    Theme,
    UserProfile,
    evaluate_eligibility,
)
from app.search.mapper import CatalogSearchDocument

_MAX_DIMENSIONS = 4096
_MAX_K = 100
_MAX_CANDIDATES = 10_000
_MODEL_VERSION = r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"


def _finite(values: tuple[float, ...], field_name: str) -> tuple[float, ...]:
    if any(not math.isfinite(value) for value in values):
        raise ValueError(f"{field_name} values must be finite")
    if not any(values):
        raise ValueError(f"{field_name} must not be a zero vector")
    return values


class VectorQuery(BaseModel):
    """Explicit versioned embedding query accepted by the local retriever."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    embedding: tuple[float, ...] = Field(min_length=1, max_length=_MAX_DIMENSIONS)
    embedding_model_version: str = Field(min_length=1, max_length=255, pattern=_MODEL_VERSION)
    dimensions: int = Field(ge=1, le=_MAX_DIMENSIONS)
    similarity: Literal["cosine"] = "cosine"

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(isinstance(item, bool) for item in value):
            raise ValueError("embedding values must be numeric")
        return _finite(tuple(float(item) for item in value), "query embedding")

    @model_validator(mode="after")
    def validate_dimensions(self) -> "VectorQuery":
        if len(self.embedding) != self.dimensions:
            raise ValueError("query dimensions do not match embedding length")
        return self


class VectorDocument(BaseModel):
    """Catalog document plus the version metadata supplied by an index provider."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    document: CatalogSearchDocument
    embedding: tuple[float, ...] = Field(min_length=1, max_length=_MAX_DIMENSIONS)
    embedding_model_version: str = Field(min_length=1, max_length=255, pattern=_MODEL_VERSION)
    dimensions: int = Field(ge=1, le=_MAX_DIMENSIONS)

    @field_validator("embedding")
    @classmethod
    def validate_embedding(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(isinstance(item, bool) for item in value):
            raise ValueError("embedding values must be numeric")
        return _finite(tuple(float(item) for item in value), "document embedding")

    @model_validator(mode="after")
    def validate_dimensions(self) -> "VectorDocument":
        if len(self.embedding) != self.dimensions:
            raise ValueError("document dimensions do not match embedding length")
        if len(self.document.embedding) != self.dimensions:
            raise ValueError("catalog document dimensions do not match vector dimensions")
        if tuple(self.document.embedding) != self.embedding:
            raise ValueError("provider vector does not match catalog document vector")
        return self


class VectorEvidence(BaseModel):
    """Redacted evidence explaining one vector candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)
    cosine_similarity: float = Field(ge=-1, le=1, allow_inf_nan=False)
    embedding_model_version: str = Field(min_length=1, max_length=255, pattern=_MODEL_VERSION)


class VectorRetrievalResult(BaseModel):
    """Candidate-source output and bounded evidence for one vector request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[VectorEvidence, ...] = Field(max_length=_MAX_K)
    total_matches: int = Field(ge=0, le=_MAX_CANDIDATES)

    @model_validator(mode="after")
    def validate_alignment(self) -> "VectorRetrievalResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


@dataclass(frozen=True)
class _ScoredVector:
    item: VectorDocument
    score: float


class VectorRetriever:
    """Search local vector records without contacting OpenSearch or an embedder."""

    source = "vector"
    source_version = "imd-vector-v1"

    def retrieve(
        self,
        query: VectorQuery,
        documents: Iterable[VectorDocument],
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
        *,
        k: int = 20,
        source_version: str | None = None,
    ) -> VectorRetrievalResult:
        if k < 1 or k > _MAX_K:
            raise ValueError(f"k must be between 1 and {_MAX_K}")
        version = source_version or self.source_version
        docs = tuple(documents)
        if len(docs) > _MAX_CANDIDATES:
            raise ValueError(f"documents cannot exceed {_MAX_CANDIDATES} records")
        compatible = tuple(
            doc
            for doc in docs
            if doc.embedding_model_version == query.embedding_model_version
            and doc.dimensions == query.dimensions
        )
        eligible = tuple(
            doc for doc in compatible if self._is_eligible(doc.document, context, user)
        )
        scored = tuple(
            sorted(
                (_ScoredVector(doc, _cosine(query.embedding, doc.embedding)) for doc in eligible),
                key=lambda item: (-item.score, item.item.document.experience_id),
            )
        )
        page = scored[:k]
        candidates = tuple(
            Candidate(
                experience_id=item.item.document.experience_id,
                tenant_id=item.item.document.tenant_id,
                source=self.source,
                source_version=version,
                score=round((item.score + 1.0) / 2.0, 8),
                reason_codes=("vector_cosine",),
            )
            for item in page
        )
        evidence = tuple(
            VectorEvidence(
                experience_id=item.item.document.experience_id,
                reason_codes=("vector_cosine",),
                cosine_similarity=round(item.score, 8),
                embedding_model_version=item.item.embedding_model_version,
            )
            for item in page
        )
        has_data = bool(compatible)
        degradation = Degradation.OK if candidates else (Degradation.EMPTY if has_data else Degradation.FAILURE)
        error_code = None if degradation in {Degradation.OK, Degradation.EMPTY} else "vector_data_unavailable"
        result = CandidateSourceResult(
            source=self.source,
            source_version=version,
            tenant_id=context.request_context.tenant_id,
            request_id=context.request_context.request_id,
            candidates=candidates,
            degradation=degradation,
            error_code=error_code,
        )
        return VectorRetrievalResult(
            source_result=result,
            evidence=evidence,
            total_matches=len(scored) if has_data else 0,
        )

    @staticmethod
    def _is_eligible(
        document: CatalogSearchDocument,
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
    ) -> bool:
        if document.blocked or document.tenant_id != context.request_context.tenant_id:
            return False
        record = ExperienceRecord(
            experience_id=document.experience_id,
            creator_id=document.creator_id,
            tenant_id=document.tenant_id,
            title=document.title,
            description=document.description,
            genres=tuple(Genre(value) for value in document.genres),
            themes=tuple(Theme(value) for value in document.themes),
            mechanics=tuple(Mechanic(value) for value in document.mechanics),
            devices=tuple(CatalogDevice(value) for value in document.devices),
            locales=tuple(Locale(value) for value in document.locales),
            age_rating=AgeRating(document.age_rating),
            safety_state=SafetyState(document.safety_state),
            availability=Availability(document.availability),
            synthetic=document.synthetic,
            provenance="synthetic" if document.synthetic else "licensed",
        )
        return evaluate_eligibility(record, user, context).eligible


def _cosine(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    if len(left) != len(right):
        raise ValueError("vectors must have matching dimensions")
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        raise ValueError("cosine similarity requires non-zero vectors")
    return sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
