from app.domain.models import (
    AgeRating,
    ConsentState,
    ExplicitPreferences,
    HistoryLength,
    Locale,
    Persona,
    UserProfile,
)
from app.policy.eligibility import EligibilityReason, compile_eligibility
from packages.platform_contracts.discovery import DiscoveryRequestContext


def _context(**overrides):
    values = {
        "tenant_id": "tenant-orbit",
        "principal_id": "user-001",
        "request_id": "request-001",
        "purpose": "recommendation",
        "locale": "en-US",
        "device": "mobile",
    }
    values.update(overrides)
    return DiscoveryRequestContext(**values)


def _user(**overrides):
    values = {
        "user_id": "user-001",
        "tenant_id": "tenant-orbit",
        "persona": Persona.EXPLICIT_PREFERENCE,
        "locale": Locale.EN_US,
        "age_rating_limit": AgeRating.E10,
        "devices": ("mobile",),
        "history_length": HistoryLength.SHORT,
        "preferences": ExplicitPreferences(),
        "consent_state": ConsentState.PERSONALIZATION_ALLOWED,
        "synthetic": True,
    }
    values.update(overrides)
    return UserProfile(**values)


def test_compiles_explicit_hard_predicates_and_blocklist():
    result = compile_eligibility(_context(), _user(), blocked_ids=("exp-9", "exp-2", "exp-9"))

    assert result.eligible is True
    assert result.reason is EligibilityReason.ALLOW
    assert result.blocked_ids == ("exp-2", "exp-9")
    assert [predicate.field for predicate in result.predicates] == [
        "tenant_id", "locale", "devices", "age_rating", "safety_state",
        "availability", "blocked", "experience_id",
    ]
    assert "score" not in str(result.provider_expression())


def test_missing_context_and_tenant_mismatch_fail_closed():
    missing = compile_eligibility(None, _user())
    mismatch = compile_eligibility(_context(), _user(tenant_id="tenant-lumen"))

    assert missing.eligible is False
    assert missing.reason is EligibilityReason.MISSING_CONTEXT
    assert mismatch.eligible is False
    assert mismatch.reason is EligibilityReason.TENANT_SCOPE_MISMATCH
    assert mismatch.predicates == ()


def test_consent_denies_personalization_without_removing_safe_eligibility():
    result = compile_eligibility(
        _context(),
        _user(consent_state=ConsentState.PERSONALIZATION_DENIED),
    )

    assert result.eligible is True
    assert result.reason is EligibilityReason.PERSONALIZATION_CONSENT_DENIED
    assert result.personalization.allowed is False
    assert result.predicates


def test_required_personalization_fails_closed():
    result = compile_eligibility(
        _context(),
        _user(consent_state=ConsentState.PERSONALIZATION_DENIED),
        require_personalization=True,
    )

    assert result.eligible is False
    assert result.reason is EligibilityReason.PERSONALIZATION_CONSENT_REQUIRED


def test_invalid_blocked_id_is_rejected():
    try:
        compile_eligibility(_context(), _user(), blocked_ids=("private/id",))
    except ValueError as error:
        assert "invalid" in str(error)
    else:
        raise AssertionError("invalid blocked ID should fail closed")
