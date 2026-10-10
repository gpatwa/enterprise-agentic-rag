"""Bounded conversational refinement for local immersive discovery."""
from __future__ import annotations

from enum import StrEnum
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.intelligence.adapter import BoundedIntentAdapter
from app.intelligence.intent import MAX_CATALOG_IDS, StructuredDiscoveryIntent
from app.query.parser import QueryConstraints

MAX_SESSION_TURNS = 8
MAX_SESSION_QUERY_LENGTH = 256
MAX_SESSION_TERMS = 16
MAX_SESSION_EXPANSIONS = 8


class RefinementOperation(StrEnum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"


class RefinementTurn(BaseModel):
    """One permitted refinement event; raw transcript is intentionally absent."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    operation: RefinementOperation
    intent: StructuredDiscoveryIntent


class RefinementSession(BaseModel):
    """Explicit, bounded state safe to retain between discovery requests."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session_version: str = "imd-refinement-v1"
    base_intent: StructuredDiscoveryIntent
    current_intent: StructuredDiscoveryIntent
    turns: tuple[RefinementTurn, ...] = Field(default_factory=tuple, max_length=MAX_SESSION_TURNS)

    @model_validator(mode="after")
    def validate_bounds(self) -> "RefinementSession":
        if len(self.current_intent.exact_terms) > MAX_SESSION_TERMS:
            raise ValueError("session exact terms exceed the permitted bound")
        if len(self.current_intent.expansions) > MAX_SESSION_EXPANSIONS:
            raise ValueError("session expansions exceed the permitted bound")
        if len(self.current_intent.explicit_catalog_ids) > MAX_CATALOG_IDS:
            raise ValueError("session catalog IDs exceed the permitted bound")
        return self


class RefinementResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    session: RefinementSession
    used_fallback: bool
    fallback_reason: str | None = None


def start_session(
    raw_query: str,
    *,
    explicit_catalog_ids: tuple[str, ...] = (),
    adapter: BoundedIntentAdapter | None = None,
) -> RefinementSession:
    """Create a session from the bounded IMD-070/071 contract."""
    resolved = (adapter or BoundedIntentAdapter()).resolve(
        raw_query,
        explicit_catalog_ids=explicit_catalog_ids,
    )
    return RefinementSession(base_intent=resolved.intent, current_intent=resolved.intent)


def refine_session(
    session: RefinementSession,
    follow_up: str,
    *,
    operation: RefinementOperation,
    adapter: BoundedIntentAdapter | None = None,
    caller_context: Mapping[str, object] | None = None,
) -> RefinementResult:
    """Apply allowlisted follow-up constraints without retaining caller context."""
    if len(follow_up) > MAX_SESSION_QUERY_LENGTH:
        raise ValueError("follow-up exceeds the session query bound")
    if len(session.turns) >= MAX_SESSION_TURNS:
        raise ValueError("session turn limit reached")

    # The context belongs to the caller and is deliberately neither inspected nor stored.
    del caller_context
    resolved = (adapter or BoundedIntentAdapter()).resolve(
        follow_up,
        explicit_catalog_ids=session.current_intent.explicit_catalog_ids,
    )
    next_intent = _apply_operation(session.current_intent, resolved.intent, operation)
    turn = RefinementTurn(operation=operation, intent=resolved.intent)
    next_session = session.model_copy(
        update={
            "current_intent": next_intent,
            "turns": (*session.turns, turn),
        }
    )
    return RefinementResult(
        session=next_session,
        used_fallback=resolved.used_fallback,
        fallback_reason=resolved.fallback_reason,
    )


def _apply_operation(current: StructuredDiscoveryIntent, follow_up: StructuredDiscoveryIntent, operation: RefinementOperation) -> StructuredDiscoveryIntent:
    if operation is RefinementOperation.ADD:
        constraints = _merge_constraints(current.constraints, follow_up.constraints)
        exact_terms = _bounded_unique((*current.exact_terms, *follow_up.exact_terms), MAX_SESSION_TERMS)
        lexical_text = _join(current.lexical_text, follow_up.lexical_text)
    elif operation is RefinementOperation.REMOVE:
        constraints = _remove_constraints(current.constraints, follow_up.constraints)
        exact_terms = tuple(term for term in current.exact_terms if term not in follow_up.exact_terms)
        lexical_text = _remove_words(current.lexical_text, follow_up.lexical_text)
    else:
        constraints = _replace_constraints(current.constraints, follow_up.constraints)
        exact_terms = follow_up.exact_terms
        lexical_text = follow_up.lexical_text

    empty = not lexical_text and not exact_terms and constraints == QueryConstraints()
    return StructuredDiscoveryIntent(
        exact_terms=exact_terms,
        lexical_text=lexical_text,
        constraints=constraints,
        is_empty=empty,
        no_result_expected=empty,
        explicit_catalog_ids=current.explicit_catalog_ids,
    )


def _merge_constraints(current: QueryConstraints, follow_up: QueryConstraints) -> QueryConstraints:
    return QueryConstraints(
        locale=follow_up.locale or current.locale,
        device=follow_up.device or current.device,
        age_rating=follow_up.age_rating or current.age_rating,
        genres=_bounded_unique((*current.genres, *follow_up.genres), 10),
        themes=_bounded_unique((*current.themes, *follow_up.themes), 10),
    )


def _remove_constraints(current: QueryConstraints, follow_up: QueryConstraints) -> QueryConstraints:
    return QueryConstraints(
        locale=None if follow_up.locale == current.locale else current.locale,
        device=None if follow_up.device == current.device else current.device,
        age_rating=None if follow_up.age_rating == current.age_rating else current.age_rating,
        genres=tuple(item for item in current.genres if item not in follow_up.genres),
        themes=tuple(item for item in current.themes if item not in follow_up.themes),
    )


def _replace_constraints(current: QueryConstraints, follow_up: QueryConstraints) -> QueryConstraints:
    return QueryConstraints(
        locale=follow_up.locale if follow_up.locale is not None else current.locale,
        device=follow_up.device if follow_up.device is not None else current.device,
        age_rating=follow_up.age_rating if follow_up.age_rating is not None else current.age_rating,
        genres=follow_up.genres if follow_up.genres else current.genres,
        themes=follow_up.themes if follow_up.themes else current.themes,
    )


def _bounded_unique(values: tuple[object, ...], limit: int) -> tuple:
    return tuple(dict.fromkeys(values))[:limit]


def _join(left: str, right: str) -> str:
    return " ".join(part for part in (left, right) if part)[:MAX_SESSION_QUERY_LENGTH]


def _remove_words(left: str, right: str) -> str:
    removed = set(right.casefold().split())
    return " ".join(word for word in left.split() if word.casefold() not in removed)


__all__ = [
    "MAX_SESSION_TURNS",
    "RefinementOperation",
    "RefinementResult",
    "RefinementSession",
    "RefinementTurn",
    "refine_session",
    "start_session",
]
