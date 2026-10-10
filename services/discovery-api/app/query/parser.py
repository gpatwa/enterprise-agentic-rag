"""Bounded, deterministic parsing for immersive discovery queries."""
from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.models import AgeRating, CatalogDevice, Genre, Locale, Theme

QUERY_VERSION = "imd-query-v1"
MAX_QUERY_LENGTH = 256
MAX_QUERY_TOKENS = 32
MAX_EXACT_TERMS = 16

_TOKEN = re.compile(r"[\w]+(?:[-.:][\w]+)*", re.UNICODE)
_QUOTED = re.compile(r'["\']([^"\']{1,128})["\']')


class QueryConstraints(BaseModel):
    """Only constraints represented by the discovery domain are accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    locale: Locale | None = None
    device: CatalogDevice | None = None
    age_rating: AgeRating | None = None
    genres: tuple[Genre, ...] = Field(default_factory=tuple, max_length=10)
    themes: tuple[Theme, ...] = Field(default_factory=tuple, max_length=10)


class ParsedQuery(BaseModel):
    """Versioned parser output safe to pass to downstream retrieval."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    query_version: str = QUERY_VERSION
    exact_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_EXACT_TERMS)
    lexical_text: str = Field(default="", max_length=MAX_QUERY_LENGTH)
    constraints: QueryConstraints = Field(default_factory=QueryConstraints)
    is_empty: bool = False
    no_result_expected: bool = False

    @model_validator(mode="after")
    def validate_indicators(self) -> "ParsedQuery":
        if self.is_empty != self.no_result_expected:
            raise ValueError("empty and no-result indicators must agree")
        if self.is_empty and (self.exact_terms or self.lexical_text or self.constraints != QueryConstraints()):
            raise ValueError("empty query cannot contain parsed content")
        return self


class QueryParser:
    """Parse text without profiles, model calls, external state, or execution."""

    version = QUERY_VERSION

    def parse(self, raw_query: str) -> ParsedQuery:
        if not isinstance(raw_query, str):
            raise TypeError("raw_query must be a string")
        if len(raw_query) > MAX_QUERY_LENGTH:
            raise ValueError(f"raw_query cannot exceed {MAX_QUERY_LENGTH} characters")

        normalized = _normalize(raw_query)
        tokens = _TOKEN.findall(normalized)
        if len(tokens) > MAX_QUERY_TOKENS:
            raise ValueError(f"raw_query cannot exceed {MAX_QUERY_TOKENS} tokens")
        if not tokens:
            return ParsedQuery(is_empty=True, no_result_expected=True)

        constraints, consumed = _extract_constraints(tokens)
        exact_terms = _exact_terms(raw_query, tokens, consumed)
        lexical_tokens = tuple(
            token
            for index, token in enumerate(tokens)
            if index not in consumed
        )
        lexical_text = " ".join(lexical_tokens)
        return ParsedQuery(
            exact_terms=exact_terms,
            lexical_text=lexical_text,
            constraints=constraints,
            is_empty=False,
            no_result_expected=False,
        )


def parse_query(raw_query: str) -> ParsedQuery:
    """Convenience entry point for deterministic query parsing."""
    return QueryParser().parse(raw_query)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = "".join(character if character.isprintable() else " " for character in value)
    return " ".join(value.casefold().split())


def _extract_constraints(tokens: tuple[str, ...]) -> tuple[QueryConstraints, set[int]]:
    consumed: set[int] = set()
    locale = _unique_match(tokens, {item.value.casefold(): item for item in Locale})
    device = _unique_match(tokens, {item.value.casefold(): item for item in CatalogDevice})
    age = _unique_match(tokens, {"e10": AgeRating.E10, "teen": AgeRating.T, "everyone": AgeRating.E})
    genres = _all_matches(tokens, {item.value.casefold(): item for item in Genre})
    themes = _all_matches(tokens, {item.value.casefold(): item for item in Theme})

    for index, token in enumerate(tokens):
        if locale is not None and token == locale.value.casefold():
            consumed.add(index)
        if device is not None and token == device.value.casefold():
            consumed.add(index)
        if age is not None and token in {"e10", "teen", "everyone"}:
            consumed.add(index)
        if token in {item.value.casefold() for item in genres} or token in {item.value.casefold() for item in themes}:
            consumed.add(index)
    return QueryConstraints(locale=locale, device=device, age_rating=age, genres=genres, themes=themes), consumed


def _unique_match(tokens: Iterable[str], allowlist: dict[str, object]) -> object | None:
    matches = {allowlist[token] for token in tokens if token in allowlist}
    return next(iter(matches)) if len(matches) == 1 else None


def _all_matches(tokens: Iterable[str], allowlist: dict[str, object]) -> tuple:
    return tuple(dict.fromkeys(allowlist[token] for token in tokens if token in allowlist))


def _exact_terms(raw_query: str, tokens: tuple[str, ...], consumed: set[int]) -> tuple[str, ...]:
    terms: list[str] = [" ".join(match.group(1).split()) for match in _QUOTED.finditer(raw_query)]
    for index, token in enumerate(tokens):
        if index in consumed:
            continue
        if any(character.isdigit() for character in token) or any(character in token for character in "-_.:"):
            terms.append(token)
    return tuple(dict.fromkeys(term for term in terms if term))[:MAX_EXACT_TERMS]
