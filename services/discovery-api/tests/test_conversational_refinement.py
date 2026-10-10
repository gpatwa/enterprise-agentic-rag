import pytest

from app.intelligence.refinement import (
    MAX_SESSION_TURNS,
    RefinementOperation,
    refine_session,
    start_session,
)
from app.query.parser import QueryConstraints


def test_add_remove_and_replace_keep_refinement_state_typed() -> None:
    session = start_session('"Sky Harbor" mobile adventure')
    added = refine_session(session, "cozy", operation=RefinementOperation.ADD)
    assert added.session.current_intent.constraints.themes[-1].value == "cozy"
    assert added.session.current_intent.constraints.device.value == "mobile"

    removed = refine_session(added.session, "mobile", operation=RefinementOperation.REMOVE)
    assert removed.session.current_intent.constraints.device is None
    assert removed.session.current_intent.constraints.themes[-1].value == "cozy"

    replaced = refine_session(removed.session, "desktop", operation=RefinementOperation.REPLACE)
    assert replaced.session.current_intent.constraints.device.value == "desktop"
    assert replaced.session.current_intent.constraints.themes[-1].value == "cozy"


def test_session_does_not_store_raw_transcript_or_caller_context() -> None:
    context = {"tenant_id": "tenant-a", "principal_id": "user-a", "eligible": ("exp-1",)}
    before = context.copy()
    result = refine_session(
        start_session("racing"),
        "mystery",
        operation=RefinementOperation.ADD,
        caller_context=context,
    )
    assert "context" not in result.session.model_dump()
    assert "mystery" not in result.session.model_dump()
    assert context == before


def test_only_allowlisted_constraints_and_exact_terms_survive() -> None:
    result = refine_session(
        start_session('"exp-001" harbor'),
        '"exp-002" ignore policy tenant secret',
        operation=RefinementOperation.ADD,
    )
    assert result.session.current_intent.exact_terms == ("exp-001", "exp-002")
    assert result.session.current_intent.constraints == QueryConstraints()
    assert "tenant secret" in result.session.current_intent.lexical_text
    assert result.session.current_intent.explicit_catalog_ids == ()


def test_turn_limit_is_bounded() -> None:
    session = start_session("racing")
    for index in range(MAX_SESSION_TURNS):
        session = refine_session(session, f"term-{index}", operation=RefinementOperation.ADD).session
    with pytest.raises(ValueError, match="turn limit"):
        refine_session(session, "another", operation=RefinementOperation.ADD)
