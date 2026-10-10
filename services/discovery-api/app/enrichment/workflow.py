"""Provenance-preserving, review-gated metadata enrichment.

Enrichment is deliberately a derived workflow. It never mutates an
authoritative ``ExperienceRecord`` and it exposes no action or policy fields
that could turn catalog text into instructions.
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from hashlib import sha256
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.models import ExperienceRecord

MAX_TAGS = 12
MAX_TAG_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1_000
MAX_SOURCE_LENGTH = 8_000


class EnrichmentStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"


class _EnrichmentModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
        strict=True,
    )


def _validate_printable(value: str, *, field_name: str, max_length: int) -> str:
    if not value.strip():
        raise ValueError(f"{field_name} must be non-blank")
    if len(value) > max_length:
        raise ValueError(f"{field_name} cannot exceed {max_length} characters")
    if any(not character.isprintable() for character in value):
        raise ValueError(f"{field_name} must contain printable text only")
    return value


class EnrichmentProposal(_EnrichmentModel):
    """Untrusted provider output containing only permitted derived fields."""

    generated_tags: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_TAGS)
    generated_description: str | None = Field(default=None, max_length=MAX_DESCRIPTION_LENGTH)

    @field_validator("generated_tags", mode="before")
    @classmethod
    def deduplicate_tags(cls, value: object) -> object:
        if isinstance(value, (tuple, list)):
            return tuple(dict.fromkeys(value))
        return value

    @field_validator("generated_tags")
    @classmethod
    def validate_tags(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(
            _validate_printable(tag, field_name="generated_tags", max_length=MAX_TAG_LENGTH).strip()
            for tag in value
        )

    @field_validator("generated_description")
    @classmethod
    def validate_description(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return _validate_printable(value, field_name="generated_description", max_length=MAX_DESCRIPTION_LENGTH)


class EnrichmentDraft(_EnrichmentModel):
    """Reviewable derived metadata with enough provenance to reproduce it."""

    tenant_id: str = Field(min_length=1, max_length=255)
    experience_id: str = Field(min_length=1, max_length=255)
    source_content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    proposal: EnrichmentProposal
    provider_name: str = Field(min_length=1, max_length=128)
    model_version: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=128)
    generated_at: datetime
    status: EnrichmentStatus = EnrichmentStatus.DRAFT
    reviewer_id: str | None = Field(default=None, max_length=255)
    review_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_draft(self) -> "EnrichmentDraft":
        if self.generated_at.tzinfo is None or self.generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        if self.status is EnrichmentStatus.DRAFT and (self.reviewer_id or self.review_reason):
            raise ValueError("drafts cannot contain review metadata")
        if self.status is not EnrichmentStatus.DRAFT and not self.reviewer_id:
            raise ValueError("reviewed enrichment must identify a reviewer")
        if self.status is not EnrichmentStatus.DRAFT and not self.review_reason:
            raise ValueError("reviewed enrichment must contain a reason")
        return self


class EnrichmentProvider(Protocol):
    """Provider boundary; source text is untrusted data, never instructions."""

    def generate(self, source_text: str) -> object:
        """Return only candidate derived metadata for the supplied source data."""


class ScriptedEnrichmentProvider:
    """Deterministic fake provider for local demos and model-off operation."""

    def __init__(self, proposal: EnrichmentProposal | None = None) -> None:
        self.proposal = proposal or EnrichmentProposal(generated_tags=("exploration",))
        self.calls = 0

    def generate(self, source_text: str) -> object:
        self.calls += 1
        return self.proposal.model_dump()


class ProvenanceEnrichmentWorkflow:
    """Create drafts and explicit review transitions without catalog mutation."""

    def __init__(
        self,
        provider: EnrichmentProvider | None = None,
        *,
        provider_name: str = "model_off",
        model_version: str = "none",
        prompt_version: str = "imd-enrichment-v1",
    ) -> None:
        self.provider = provider
        self.provider_name = provider_name
        self.model_version = model_version
        self.prompt_version = prompt_version

    def propose(
        self,
        record: ExperienceRecord,
        *,
        caller_tenant_id: str,
        source_text: str,
        generated_at: datetime,
    ) -> EnrichmentDraft:
        """Create a draft while preserving caller ownership and authority."""
        if record.tenant_id != caller_tenant_id:
            raise ValueError("caller tenant does not own catalog record")
        _validate_printable(source_text, field_name="source_text", max_length=MAX_SOURCE_LENGTH)
        if generated_at.tzinfo is None or generated_at.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        proposal = EnrichmentProposal()
        if self.provider is not None:
            try:
                proposal = EnrichmentProposal.model_validate(self.provider.generate(source_text))
            except Exception:
                proposal = EnrichmentProposal()
        return EnrichmentDraft(
            tenant_id=caller_tenant_id,
            experience_id=record.experience_id,
            source_content_hash=sha256(source_text.encode("utf-8")).hexdigest(),
            proposal=proposal,
            provider_name=self.provider_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            generated_at=generated_at,
        )

    @staticmethod
    def approve(draft: EnrichmentDraft, *, reviewer_id: str, reason: str) -> EnrichmentDraft:
        """Record explicit approval; callers must apply derived fields separately."""
        if draft.status is not EnrichmentStatus.DRAFT:
            raise ValueError("only draft enrichment can be approved")
        return draft.model_copy(
            update={
                "status": EnrichmentStatus.APPROVED,
                "reviewer_id": reviewer_id,
                "review_reason": reason,
            }
        )

    @staticmethod
    def reject(draft: EnrichmentDraft, *, reviewer_id: str, reason: str) -> EnrichmentDraft:
        """Record explicit rejection without deleting provenance."""
        if draft.status is not EnrichmentStatus.DRAFT:
            raise ValueError("only draft enrichment can be rejected")
        return draft.model_copy(
            update={
                "status": EnrichmentStatus.REJECTED,
                "reviewer_id": reviewer_id,
                "review_reason": reason,
            }
        )


__all__ = [
    "EnrichmentDraft",
    "EnrichmentProposal",
    "EnrichmentProvider",
    "EnrichmentStatus",
    "ProvenanceEnrichmentWorkflow",
    "ScriptedEnrichmentProvider",
]
