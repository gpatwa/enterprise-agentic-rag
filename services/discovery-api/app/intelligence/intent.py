"""Strict, provider-independent contract for optional discovery intent."""
from __future__ import annotations

from collections.abc import Iterable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.query.parser import MAX_EXACT_TERMS, MAX_QUERY_LENGTH, ParsedQuery, QueryConstraints, parse_query

INTENT_VERSION = "imd-intent-v1"
MAX_EXPANSIONS = 8
MAX_EXPANSION_LENGTH = 64
MAX_EXPANSION_TOTAL = 512
MAX_CATALOG_IDS = 16
MAX_CATALOG_ID_LENGTH = 255


def _validate_texts(
    values: tuple[str, ...],
    *,
    field_name: str,
    max_length: int,
) -> tuple[str, ...]:
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{field_name} entries must be non-blank strings")
        if len(value) > max_length:
            raise ValueError(f"{field_name} entries cannot exceed {max_length} characters")
        if any(not character.isprintable() for character in value):
            raise ValueError(f"{field_name} entries must contain printable text only")
    return values


class StructuredDiscoveryIntent(BaseModel):
    """Safe optional intent output layered on top of deterministic parsing.

    Identity, tenant, safety, eligibility, and authoritative catalog fields are
    deliberately absent. Retrieval and policy code must continue to source those
    values from the request and catalog contracts.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    intent_version: str = INTENT_VERSION
    exact_terms: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_EXACT_TERMS)
    lexical_text: str = Field(default="", max_length=MAX_QUERY_LENGTH)
    constraints: QueryConstraints = Field(default_factory=QueryConstraints)
    is_empty: bool = False
    no_result_expected: bool = False
    explicit_catalog_ids: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_CATALOG_IDS)
    expansions: tuple[str, ...] = Field(default_factory=tuple, max_length=MAX_EXPANSIONS)

    @field_validator("exact_terms")
    @classmethod
    def validate_exact_terms(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_texts(values, field_name="exact_terms", max_length=MAX_QUERY_LENGTH)

    @field_validator("explicit_catalog_ids")
    @classmethod
    def validate_catalog_ids(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _validate_texts(values, field_name="explicit_catalog_ids", max_length=MAX_CATALOG_ID_LENGTH)

    @field_validator("expansions", mode="before")
    @classmethod
    def deduplicate_expansions(cls, values: object) -> object:
        if isinstance(values, (tuple, list)):
            return tuple(dict.fromkeys(values))
        return values

    @field_validator("expansions")
    @classmethod
    def validate_expansions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        values = _validate_texts(values, field_name="expansions", max_length=MAX_EXPANSION_LENGTH)
        if len(" ".join(values)) > MAX_EXPANSION_TOTAL:
            raise ValueError(f"expansions cannot exceed {MAX_EXPANSION_TOTAL} total characters")
        return tuple(value.strip() for value in values)

    @field_validator("lexical_text")
    @classmethod
    def validate_lexical_text(cls, value: str) -> str:
        if any(not character.isprintable() for character in value):
            raise ValueError("lexical_text must contain printable text only")
        return value

    @model_validator(mode="after")
    def validate_version(self) -> "StructuredDiscoveryIntent":
        if self.intent_version != INTENT_VERSION:
            raise ValueError(f"intent_version must be {INTENT_VERSION}")
        if self.is_empty != self.no_result_expected:
            raise ValueError("empty and no-result indicators must agree")
        if self.is_empty and (self.exact_terms or self.lexical_text or self.constraints != QueryConstraints()):
            raise ValueError("empty intent cannot contain parsed content")
        if len(self.expansions) > MAX_EXPANSIONS:
            raise ValueError(f"expansions cannot exceed {MAX_EXPANSIONS} items")
        return self

    @classmethod
    def from_parsed_query(
        cls,
        parsed_query: ParsedQuery,
        *,
        expansions: Iterable[str] = (),
        explicit_catalog_ids: Iterable[str] = (),
    ) -> "StructuredDiscoveryIntent":
        """Attach bounded optional intelligence without changing parser output."""
        return cls(
            exact_terms=parsed_query.exact_terms,
            lexical_text=parsed_query.lexical_text,
            constraints=parsed_query.constraints,
            is_empty=parsed_query.is_empty,
            no_result_expected=parsed_query.no_result_expected,
            explicit_catalog_ids=tuple(explicit_catalog_ids),
            expansions=tuple(expansions),
        )

    def preserves(self, parsed_query: ParsedQuery) -> bool:
        """Return whether parser-owned query meaning is unchanged."""
        return (
            self.exact_terms == parsed_query.exact_terms
            and self.lexical_text == parsed_query.lexical_text
            and self.constraints == parsed_query.constraints
        )


def build_intent(
    raw_query: str,
    *,
    expansions: Iterable[str] = (),
    explicit_catalog_ids: Iterable[str] = (),
) -> StructuredDiscoveryIntent:
    """Build an intent deterministically; no provider or network is involved."""
    return StructuredDiscoveryIntent.from_parsed_query(
        parse_query(raw_query),
        expansions=expansions,
        explicit_catalog_ids=explicit_catalog_ids,
    )
