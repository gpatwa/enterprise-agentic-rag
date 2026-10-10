import json
from datetime import datetime, timezone
from pathlib import Path

from app.domain.models import ImmersiveDiscoveryContext, UserProfile
from app.search.lexical import LexicalRetriever
from app.search.mapper import CatalogDocumentInput, map_catalog_document
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden"


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


def _document(index: int, **overrides):
    raw = json.loads((FIXTURE / "experiences.json").read_text())[index]
    raw.update(overrides)
    from app.domain.models import ExperienceRecord

    record = ExperienceRecord.model_validate(raw)
    return map_catalog_document(
        CatalogDocumentInput(
            record=record,
            tenant_id=record.tenant_id,
            source_type="fixture",
            source_id=record.experience_id,
            provenance_ref=f"fixture://{record.experience_id}",
            content_version="v1",
            permission_version="v1",
            embedding=tuple(0.01 for _ in range(384)),
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    )


def test_exact_id_precedes_lexical_matches_and_returns_redacted_evidence():
    documents = (_document(0), _document(1))
    result = LexicalRetriever().retrieve("exp-001", documents, _context(), _user())

    assert result.source_result.candidates[0].experience_id == "exp-001"
    assert result.source_result.candidates[0].reason_codes == ("exact_id",)
    assert result.evidence[0].matched_fields == ("experience_id",)
    assert "user_id" not in result.evidence[0].model_dump()


def test_title_phrase_and_terms_are_scored_deterministically_with_stable_ties():
    documents = (_document(0), _document(1))
    first = LexicalRetriever().retrieve("Lantern Harbor", documents, _context(), _user())
    second = LexicalRetriever().retrieve("Lantern Harbor", tuple(reversed(documents)), _context(), _user())

    assert first.source_result.model_dump() == second.source_result.model_dump()
    assert first.evidence[0].phrase_match is True
    assert "title" in first.evidence[0].matched_fields


def test_hard_scope_and_eligibility_filters_run_before_scoring():
    documents = (
        _document(0),
        _document(1, tenant_id="tenant-other"),
        _document(2, locales=("fr-FR",)),
    )
    result = LexicalRetriever().retrieve("mystery", documents, _context(), _user())

    assert all(item.tenant_id == "tenant-orbit" for item in result.source_result.candidates)
    assert {item.experience_id for item in result.source_result.candidates} == {"exp-001"}


def test_empty_results_and_pagination_are_bounded():
    documents = (_document(0), _document(1))
    empty = LexicalRetriever().retrieve("does-not-exist", documents, _context(), _user())
    page = LexicalRetriever().retrieve(
        "mystery", documents, _context(), _user(),
    )

    assert empty.source_result.degradation.value == "empty"
    assert empty.total_matches == 0
    assert len(page.source_result.candidates) <= 20
