import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import ImmersiveDiscoveryContext, UserProfile
from app.search.mapper import CatalogDocumentInput, map_catalog_document
from app.search.vector import VectorDocument, VectorQuery, VectorRetriever
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden"
MODEL_VERSION = "imd-text-embedding-v1"


def _embedding(first: float, second: float) -> tuple[float, ...]:
    return (first, second) + (0.0,) * 382


def _context(**overrides):
    values = dict(
        tenant_id="tenant-orbit",
        principal_id="user-001",
        request_id="request-001",
        purpose="search",
        locale="en-US",
        device="web",
        age=16,
    )
    values.update(overrides)
    return ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(**values),
        surface="search",
    )


def _user(**overrides):
    values = dict(
        user_id="user-001",
        tenant_id="tenant-orbit",
        persona="short-history",
        locale="en-US",
        age_rating_limit="T",
        devices=("desktop",),
        history_length="short",
        preferences={"genres": (), "themes": ()},
        consent_state="personalization_allowed",
        synthetic=True,
    )
    values.update(overrides)
    return UserProfile(**values)


def _document(index: int, vector: tuple[float, ...], **overrides):
    vector = tuple(vector) + (0.0,) * (384 - len(vector))
    raw = json.loads((FIXTURE / "experiences.json").read_text())[index]
    raw.update(overrides)
    from app.domain.models import ExperienceRecord

    record = ExperienceRecord.model_validate(raw)
    document = map_catalog_document(
        CatalogDocumentInput(
            record=record,
            tenant_id=record.tenant_id,
            source_type="fixture",
            source_id=record.experience_id,
            provenance_ref=f"fixture://{record.experience_id}",
            content_version="v1",
            permission_version="v1",
            embedding=vector,
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    )
    return VectorDocument(
        document=document,
        embedding=vector,
        embedding_model_version=MODEL_VERSION,
        dimensions=len(vector),
    )


def test_vector_query_requires_explicit_matching_dimensions_and_finite_values():
    with pytest.raises(ValidationError):
        VectorQuery(embedding=(1.0, 0.0), dimensions=3, embedding_model_version=MODEL_VERSION)
    with pytest.raises(ValidationError):
        VectorQuery(embedding=(float("nan"), 0.0), dimensions=2, embedding_model_version=MODEL_VERSION)


def test_cosine_retrieval_is_deterministic_and_returns_redacted_evidence():
    documents = (
        _document(0, _embedding(1.0, 0.0)),
        _document(1, _embedding(0.0, 1.0)),
    )
    query = VectorQuery(
        embedding=_embedding(1.0, 0.0),
        dimensions=384,
        embedding_model_version=MODEL_VERSION,
    )

    first = VectorRetriever().retrieve(query, documents, _context(), _user())
    second = VectorRetriever().retrieve(query, tuple(reversed(documents)), _context(), _user())

    assert first.source_result.model_dump() == second.source_result.model_dump()
    assert first.source_result.candidates[0].experience_id == "exp-001"
    assert first.evidence[0].cosine_similarity == 1.0
    assert "user_id" not in first.evidence[0].model_dump()


def test_hard_filters_run_before_scoring_and_mixed_versions_are_ignored():
    documents = (
        _document(0, _embedding(1.0, 0.0)),
        _document(1, _embedding(1.0, 0.0), tenant_id="tenant-other"),
        _document(2, _embedding(1.0, 0.0), locales=("fr-FR",)),
    )
    mismatched = _document(0, _embedding(1.0, 0.0))
    mismatched = mismatched.model_copy(update={"embedding_model_version": "other-v1"})
    query = VectorQuery(
        embedding=_embedding(1.0, 0.0),
        dimensions=384,
        embedding_model_version=MODEL_VERSION,
    )

    result = VectorRetriever().retrieve(query, (*documents, mismatched), _context(), _user())

    assert {item.experience_id for item in result.source_result.candidates} == {"exp-001"}
    assert result.total_matches == 1


def test_no_compatible_vector_data_degrades_explicitly():
    document = _document(0, _embedding(1.0, 0.0))
    query = VectorQuery(
        embedding=_embedding(1.0, 0.0),
        dimensions=384,
        embedding_model_version="future-v2",
    )

    result = VectorRetriever().retrieve(query, (document,), _context(), _user())

    assert result.source_result.degradation.value == "failure"
    assert result.source_result.error_code == "vector_data_unavailable"
    assert result.source_result.candidates == ()
