"""Bounded, immutable evidence packets for resolution synthesis."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.resolution.retrieval import RetrievalProvenance
from app.resolution.safety import bound_untrusted_text
from app.search.models import SearchResult

DEFAULT_MAX_ITEMS = 20
DEFAULT_MAX_FIELD_CHARS = 2_000
DEFAULT_MAX_PACKET_CHARS = 8_000


def _version(value: Any, name: str) -> str:
    if value is None and name == "embedding_version":
        return value
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-blank version")
    return value.strip()


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    label: str
    document_id: str
    source_id: str
    source_type: str
    title: str
    snippet: str
    metadata: tuple[tuple[str, str], ...] = ()
    query: str
    retrieval_mode: str
    index_version: str
    content_version: str
    permission_version: str
    embedding_version: str | None = None

    _validate_versions = field_validator(
        "index_version", "content_version", "permission_version", "embedding_version", mode="before"
    )(_version)


class EvidencePacket(BaseModel):
    """Frozen synthesis input containing only authorized retrieval evidence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    packet_version: str
    items: tuple[EvidenceItem, ...] = Field(max_length=DEFAULT_MAX_ITEMS)

    _validate_packet_version = field_validator("packet_version", mode="before")(_version)


def _bounded_metadata(metadata: Mapping[str, Any], limit: int) -> tuple[tuple[str, str], ...]:
    if not isinstance(metadata, Mapping):
        raise ValueError("metadata must be a mapping")
    fields: list[tuple[str, str]] = []
    for key in sorted(metadata):
        if not isinstance(key, str) or not key.strip():
            raise ValueError("metadata keys must be non-blank strings")
        fields.append((bound_untrusted_text(key, limit), bound_untrusted_text(metadata[key], limit)))
    return tuple(fields)


def build_evidence_packet(
    results: Sequence[SearchResult],
    provenance: Sequence[RetrievalProvenance],
    *,
    packet_version: str = "evidence-v1",
    max_items: int = DEFAULT_MAX_ITEMS,
    field_limit: int = DEFAULT_MAX_FIELD_CHARS,
    max_packet_chars: int = DEFAULT_MAX_PACKET_CHARS,
) -> EvidencePacket:
    """Build deterministic labels from an already authorized result set."""
    _version(packet_version, "packet_version")
    if not 1 <= max_items <= DEFAULT_MAX_ITEMS or field_limit < 1 or max_packet_chars < 1:
        raise ValueError("invalid evidence packet bounds")
    if len(results) != len(provenance) or len(results) > max_items:
        raise ValueError("results and provenance must be paired and bounded")

    seen: set[str] = set()
    items: list[EvidenceItem] = []
    used = len(packet_version)
    for index, (result, source) in enumerate(zip(results, provenance), start=1):
        if not isinstance(result, SearchResult) or not isinstance(source, RetrievalProvenance):
            raise TypeError("evidence must contain SearchResult and RetrievalProvenance instances")
        if result.document_id in seen:
            raise ValueError("duplicate document IDs are not allowed")
        if source.document_id != result.document_id:
            raise ValueError("provenance document ID does not match result")
        seen.add(result.document_id)
        snippet = bound_untrusted_text(result.text, field_limit)
        title = bound_untrusted_text(result.title, field_limit)
        metadata = _bounded_metadata(result.metadata, field_limit)
        item = EvidenceItem(
            label=f"[E{index}]", document_id=result.document_id, source_id=result.source_id,
            source_type=result.source_type, title=title, snippet=snippet, metadata=metadata,
            query=source.query, retrieval_mode=source.mode.value, index_version=result.index_generation,
            content_version=result.content_version, permission_version=result.permission_version,
            embedding_version=result.embedding_model_version,
        )
        used += sum(len(str(value)) for value in item.model_dump().values())
        if used > max_packet_chars:
            raise ValueError("evidence packet exceeds maximum size")
        items.append(item)
    return EvidencePacket(packet_version=packet_version, items=tuple(items))


__all__ = ["EvidenceItem", "EvidencePacket", "build_evidence_packet"]
