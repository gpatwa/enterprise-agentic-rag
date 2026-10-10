"""Deterministic exact and BM25-like retrieval over catalog documents."""
from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

_TOKEN = re.compile(r"[\w]+", re.UNICODE)
_MAX_QUERY_LENGTH = 256
_MAX_PAGE_SIZE = 100


class LexicalQuery(BaseModel):
    """Bounded query and pagination values accepted by the local retriever."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    text: str = Field(min_length=1, max_length=_MAX_QUERY_LENGTH)
    page: int = Field(default=1, ge=1, le=10_000)
    page_size: int = Field(default=20, ge=1, le=_MAX_PAGE_SIZE)

    @model_validator(mode="after")
    def validate_text(self) -> "LexicalQuery":
        if not _normalize(self.text):
            raise ValueError("query text must contain searchable characters")
        return self


class LexicalEvidence(BaseModel):
    """Redacted evidence explaining one lexical candidate."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    experience_id: str = Field(min_length=1, max_length=255)
    matched_fields: tuple[str, ...] = Field(min_length=1, max_length=8)
    reason_codes: tuple[str, ...] = Field(min_length=1, max_length=8)
    exact_match: bool
    phrase_match: bool
    lexical_score: float = Field(ge=0, allow_inf_nan=False)


class LexicalRetrievalResult(BaseModel):
    """Candidate-source output and bounded evidence for one request."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    source_result: CandidateSourceResult
    evidence: tuple[LexicalEvidence, ...] = Field(max_length=_MAX_PAGE_SIZE)
    total_matches: int = Field(ge=0, le=1_000_000)

    @model_validator(mode="after")
    def validate_alignment(self) -> "LexicalRetrievalResult":
        candidate_ids = tuple(item.experience_id for item in self.source_result.candidates)
        evidence_ids = tuple(item.experience_id for item in self.evidence)
        if candidate_ids != evidence_ids:
            raise ValueError("candidate and evidence order must match")
        return self


@dataclass(frozen=True)
class _ScoredDocument:
    document: CatalogSearchDocument
    score: float
    fields: tuple[str, ...]
    reasons: tuple[str, ...]
    exact: bool
    phrase: bool


class LexicalRetriever:
    """Search mapped documents without contacting OpenSearch or another provider."""

    source = "lexical"
    source_version = "imd-lexical-v1"

    def retrieve(
        self,
        query: str | LexicalQuery,
        documents: Iterable[CatalogSearchDocument],
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
        *,
        source_version: str | None = None,
    ) -> LexicalRetrievalResult:
        request = query if isinstance(query, LexicalQuery) else LexicalQuery(text=query)
        version = source_version or self.source_version
        docs = tuple(documents)
        eligible = tuple(
            document
            for document in docs
            if self._is_eligible(document, context, user)
        )
        scored = self._score(request.text, eligible)
        scored = tuple(sorted(scored, key=lambda item: (-item.score, item.document.experience_id)))
        start = (request.page - 1) * request.page_size
        page = scored[start : start + request.page_size]
        max_score = scored[0].score if scored else 0.0
        candidates = tuple(
            Candidate(
                experience_id=item.document.experience_id,
                tenant_id=item.document.tenant_id,
                source=self.source,
                source_version=version,
                score=_bounded_score(item.score, max_score),
                reason_codes=item.reasons,
            )
            for item in page
        )
        evidence = tuple(
            LexicalEvidence(
                experience_id=item.document.experience_id,
                matched_fields=item.fields,
                reason_codes=item.reasons,
                exact_match=item.exact,
                phrase_match=item.phrase,
                lexical_score=round(item.score, 8),
            )
            for item in page
        )
        result = CandidateSourceResult(
            source=self.source,
            source_version=version,
            tenant_id=context.request_context.tenant_id,
            request_id=context.request_context.request_id,
            candidates=candidates,
            degradation=Degradation.OK if candidates else Degradation.EMPTY,
        )
        return LexicalRetrievalResult(
            source_result=result,
            evidence=evidence,
            total_matches=len(scored),
        )

    @staticmethod
    def _is_eligible(
        document: CatalogSearchDocument,
        context: ImmersiveDiscoveryContext,
        user: UserProfile,
    ) -> bool:
        if document.blocked or document.tenant_id != context.request_context.tenant_id:
            return False
        record = _record_from_document(document)
        return evaluate_eligibility(record, user, context).eligible

    @staticmethod
    def _score(
        query: str,
        documents: tuple[CatalogSearchDocument, ...],
    ) -> tuple[_ScoredDocument, ...]:
        normalized_query = _normalize(query)
        query_tokens = _tokens(normalized_query)
        if not query_tokens:
            return ()
        document_tokens = {doc.experience_id: _field_tokens(doc) for doc in documents}
        document_frequency = Counter(
            token
            for fields in document_tokens.values()
            for token in set(token for values in fields.values() for token in values)
        )
        total = len(documents)
        results: list[_ScoredDocument] = []
        for document in documents:
            fields = document_tokens[document.experience_id]
            exact_id = normalized_query in {
                _normalize(document.experience_id),
                _normalize(document.experience_id_normalized),
            }
            exact_creator = normalized_query == _normalize(document.creator_id)
            phrase = _contains_phrase(normalized_query, _normalize(document.title))
            matched_fields: list[str] = []
            reasons: list[str] = []
            score = 0.0
            if exact_id:
                score += 100.0
                matched_fields.append("experience_id")
                reasons.append("exact_id")
            if exact_creator:
                score += 90.0
                matched_fields.append("creator_id")
                reasons.append("exact_creator")
            if phrase:
                score += 12.0
                matched_fields.append("title")
                reasons.append("title_phrase")
            for field, weight in (("title", 5.0), ("tags", 3.0), ("description", 1.0)):
                field_score = 0.0
                for token in query_tokens:
                    frequency = fields[field].count(token)
                    if frequency:
                        idf = math.log1p((total + 1) / (document_frequency[token] + 1))
                        field_score += (1.0 + math.log(frequency)) * idf * weight
                if field_score:
                    score += field_score
                    matched_fields.append(field)
                    reasons.append(f"{field}_term")
            if score:
                results.append(
                    _ScoredDocument(
                        document=document,
                        score=score,
                        fields=tuple(dict.fromkeys(matched_fields)),
                        reasons=tuple(dict.fromkeys(reasons)),
                        exact=exact_id or exact_creator,
                        phrase=phrase,
                    )
                )
        return tuple(results)


def _field_tokens(document: CatalogSearchDocument) -> dict[str, tuple[str, ...]]:
    return {
        "title": _tokens(document.title),
        "description": _tokens(document.description),
        "tags": _tokens(" ".join(document.tags)),
    }


def _record_from_document(document: CatalogSearchDocument) -> ExperienceRecord:
    """Reconstruct only the policy fields needed by the existing evaluator."""
    return ExperienceRecord(
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


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(_TOKEN.findall(_normalize(value)))


def _contains_phrase(query: str, value: str) -> bool:
    return bool(query and query in value)


def _bounded_score(score: float, maximum: float) -> float:
    if not maximum:
        return 0.0
    return min(1.0, max(0.0, round(score / maximum, 8)))
