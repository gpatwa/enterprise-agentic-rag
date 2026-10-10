import pytest
from pydantic import ValidationError

from app.resolution.models import (
    ActionProposal,
    ConfidenceLevel,
    GroundedResolutionOutcome,
    IntentConstraint,
    IntentEntity,
    QueryMode,
    QueryVariant,
    ResolutionCitation,
    ResolutionClaim,
    ResolutionStep,
    SearchPlan,
    SupportIntent,
    SupportIntentType,
)
from app.search.models import SearchScope


def _scope() -> SearchScope:
    return SearchScope(
        tenant_id=" tenant-acme ",
        principal_id=" agent-1 ",
        purpose=" support-resolution ",
        acl_tokens=("tenant:tenant-acme", "group:support"),
    )


def _variant(query: str = "export timeout") -> QueryVariant:
    return QueryVariant(query=query, mode=QueryMode.HYBRID, reason="matches the issue", confidence="medium")


def test_intent_and_plan_normalize_text_and_remain_immutable():
    intent = SupportIntent(
        intent="incident",
        entities=[{"name": " error ", "value": "  E-42  "}],
        constraints=[{"name": " account ", "value": " acme   west "}],
        exact_terms=[" E-42 "],
        reason="  ticket   describes   an error ",
        confidence="high",
    )
    scope = _scope()
    plan = SearchPlan(
        scope=scope,
        variants=[_variant("  export   timeout  ")],
        reason="  search   exact   evidence ",
        confidence="high",
    )

    assert intent.entities[0].name == "error"
    assert intent.entities[0].value == "E-42"
    assert plan.variants[0].query == "export timeout"
    assert plan.scope is scope
    assert plan.scope.tenant_id == "tenant-acme"
    with pytest.raises(ValidationError):
        plan.reason = "changed"


@pytest.mark.parametrize("model, field", [(SupportIntent, "reason"), (QueryVariant, "query")])
def test_models_reject_blank_text(model, field):
    values = {"intent": "incident", "entities": (), "constraints": (), "exact_terms": (), "reason": "why", "confidence": "low"}
    if model is QueryVariant:
        values = {"query": "query", "mode": "lexical", "reason": "why", "confidence": "low"}
    values[field] = "   "
    with pytest.raises(ValidationError):
        model(**values)


def test_plan_rejects_empty_duplicate_and_overlong_variants():
    with pytest.raises(ValidationError):
        SearchPlan(scope=_scope(), variants=[], reason="why", confidence="low")
    with pytest.raises(ValidationError):
        SearchPlan(scope=_scope(), variants=[_variant(), _variant(" EXPORT   TIMEOUT ")], reason="why", confidence="low")
    with pytest.raises(ValidationError):
        SearchPlan(scope=_scope(), variants=[_variant(str(index)) for index in range(5)], reason="why", confidence="low")


def test_models_reject_extra_fields_and_malformed_enums():
    with pytest.raises(ValidationError):
        QueryVariant(query="query", mode="provider-specific", reason="why", confidence="medium")
    with pytest.raises(ValidationError):
        SupportIntent(intent="incident", reason="why", confidence="certain", unexpected="x")


def test_plan_requires_existing_scope_and_preserves_scope():
    scope = _scope()
    plan = SearchPlan(scope=scope, variants=[_variant()], reason="why", confidence=ConfidenceLevel.MEDIUM)
    assert plan.scope is scope
    with pytest.raises(ValidationError):
        SearchPlan(scope=scope.model_dump(), variants=[_variant()], reason="why", confidence="medium")
    with pytest.raises(ValidationError):
        plan.scope = _scope()


def test_nested_models_are_provider_neutral():
    assert IntentEntity(name="id", value="A-1")
    assert IntentConstraint(name="status", value="open")
    assert SupportIntentType.HOW_TO.value == "how_to"


def _outcome() -> GroundedResolutionOutcome:
    return GroundedResolutionOutcome(
        claims=[{"text": "The export timed out", "citation_labels": ["[1]"]}],
        citations=[{"label": "[1]", "source_id": "ticket-42"}],
        steps=[{"instruction": "Retry the export", "citation_labels": ["[1]"]}],
        customer_response="Please retry the export and contact support if it fails again.",
        confidence="medium",
        abstention=False,
        next_action="suggest_agent_response",
        action_proposal={"description": "Offer guided retry assistance"},
    )


def test_grounded_resolution_contract_is_frozen_and_strict():
    outcome = _outcome()
    assert outcome.claims[0].citation_labels == ("[1]",)
    assert outcome.citations[0].source_id == "ticket-42"
    with pytest.raises(ValidationError):
        outcome.customer_response = "changed"
    with pytest.raises(ValidationError):
        GroundedResolutionOutcome(
            **outcome.model_dump(), unexpected="x"
        )


@pytest.mark.parametrize(
    "model, values",
    [
        (ResolutionClaim, {"text": " ", "citation_labels": ["[1]"]}),
        (ResolutionCitation, {"label": "[1]", "source_id": "   "}),
        (ResolutionStep, {"instruction": "retry", "citation_labels": [" "]}),
        (ActionProposal, {"description": "  "}),
    ],
)
def test_resolution_models_reject_blank_values(model, values):
    with pytest.raises(ValidationError):
        model(**values)


def test_resolution_models_require_citations_and_reject_nested_extras():
    with pytest.raises(ValidationError):
        ResolutionClaim(text="unsupported claim", citation_labels=[])
    with pytest.raises(ValidationError):
        ResolutionCitation(label="[1]", source_id=" ")
    with pytest.raises(ValidationError):
        ResolutionStep(instruction="retry", citation_labels=["[1]", "[1]"])
    with pytest.raises(ValidationError):
        ActionProposal(description="review", command_type="reset_account")

    outcome = _outcome()
    with pytest.raises(ValidationError):
        values = outcome.model_dump()
        values["action_proposal"] = {"description": "review", "risk": "high"}
        GroundedResolutionOutcome(**values)


def test_grounded_resolution_allows_empty_abstention():
    outcome = GroundedResolutionOutcome(
        claims=[],
        citations=[],
        steps=[],
        customer_response="There is not enough authorized evidence to resolve this issue.",
        confidence="low",
        abstention=True,
        next_action="route_to_human",
    )

    assert outcome.claims == ()
    assert outcome.citations == ()
    assert outcome.steps == ()


def test_grounded_resolution_rejects_empty_non_abstention():
    with pytest.raises(ValidationError):
        GroundedResolutionOutcome(
            claims=[],
            citations=[],
            steps=[],
            customer_response="A resolution is available.",
            confidence="high",
            abstention=False,
            next_action="suggest_agent_response",
        )
