import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domain.models import (
    AgeRating,
    CatalogDevice,
    EligibilityConstraints,
    EligibilityReasonCode,
    ExperienceRecord,
    ExperienceSignals,
    ImmersiveDiscoveryContext,
    Locale,
    UserProfile,
    evaluate_eligibility,
)
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURES = Path(__file__).parent / "fixtures" / "golden"


def _load(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text())


def _context(user: dict, *, surface: str = "home") -> ImmersiveDiscoveryContext:
    request_device = "tablet" if "tablet" in user["devices"] else "mobile" if "mobile" in user["devices"] else "web"
    return ImmersiveDiscoveryContext(
        request_context=DiscoveryRequestContext(
            tenant_id=user["tenant_id"],
            principal_id=user["user_id"],
            request_id="request-001",
            purpose=surface,
            locale=user["locale"],
            device=request_device,
        ),
        surface=surface,
    )


def _pair(user_id: str = "user-001", experience_id: str = "exp-001"):
    users = {item["user_id"]: item for item in _load("users.json")}
    experiences = {item["experience_id"]: item for item in _load("experiences.json")}
    user = UserProfile.model_validate(users[user_id])
    experience = ExperienceRecord.model_validate(experiences[experience_id])
    return user, experience, _context(users[user_id])


def test_golden_records_validate_and_round_trip_with_signals_separate():
    experience = ExperienceRecord.model_validate(_load("experiences.json")[0])
    user = UserProfile.model_validate(_load("users.json")[0])

    assert isinstance(experience.signals, ExperienceSignals)
    assert experience.signals.freshness_band.value == "fresh"
    assert ExperienceRecord.model_validate(experience.model_dump()) == experience
    assert UserProfile.model_validate(user.model_dump()) == user


def test_authoritative_and_derived_models_do_not_silently_merge():
    with pytest.raises(ValidationError):
        ExperienceSignals.model_validate({"freshness_band": "fresh", "title": "wrong"})
    record = ExperienceRecord.model_validate(_load("experiences.json")[0])
    assert record.signals is not None
    with pytest.raises(ValidationError):
        ExperienceRecord.model_validate({**record.model_dump(), "derived_score": 0.5})
    with pytest.raises(ValidationError):
        ExperienceRecord.model_validate({**_load("experiences.json")[0], "signals": {"freshness_band": "fresh"}})


def test_context_composes_shared_identity():
    user = _load("users.json")[0]
    context = _context(user)
    assert context.request_context.tenant_id == user["tenant_id"]
    assert context.request_context.request_id == "request-001"


@pytest.mark.parametrize(
    ("user_id", "experience_id", "reason"),
    [
        ("user-001", "exp-001", EligibilityReasonCode.ALLOW),
        ("user-009", "exp-047", EligibilityReasonCode.AGE_RATING_EXCEEDS_PROFILE_LIMIT),
        ("user-017", "exp-048", EligibilityReasonCode.EXPERIENCE_UNAVAILABLE),
        ("user-010", "exp-010", EligibilityReasonCode.LOCALE_NOT_SUPPORTED),
        ("user-006", "exp-009", EligibilityReasonCode.DEVICE_NOT_SUPPORTED),
    ],
)
def test_eligibility_reason_codes_are_stable(user_id, experience_id, reason):
    user, experience, context = _pair(user_id, experience_id)
    if reason is EligibilityReasonCode.AGE_RATING_EXCEEDS_PROFILE_LIMIT:
        experience = experience.model_copy(update={"tenant_id": user.tenant_id})
    decision = evaluate_eligibility(experience, user, context)
    assert decision.reason_code is reason
    assert decision.eligible is (reason in {EligibilityReasonCode.ALLOW})


def test_restricted_safety_is_denied_independently_of_age():
    user, experience, context = _pair("user-017", "exp-047")
    constraints = EligibilityConstraints(
        tenant_id=user.tenant_id,
        locale=Locale.EN_US,
        device=CatalogDevice.MOBILE,
        age_rating_limit=AgeRating.T,
    )
    decision = evaluate_eligibility(experience, user, context, constraints)
    assert decision.reason_code is EligibilityReasonCode.SAFETY_STATE_RESTRICTED
    assert decision.eligible is False


def test_tenant_mismatch_and_missing_context_fail_closed():
    user, experience, context = _pair()
    mismatched = EligibilityConstraints(
        tenant_id="tenant-lumen",
        locale=Locale.EN_US,
        device=CatalogDevice.DESKTOP,
        age_rating_limit=AgeRating.E10,
    )
    assert evaluate_eligibility(experience, user, context, mismatched).reason_code is EligibilityReasonCode.TENANT_SCOPE_MISMATCH
    assert evaluate_eligibility(None, user, context).reason_code is EligibilityReasonCode.MISSING_CONTEXT


def test_invalid_request_locale_and_device_fail_closed():
    user, experience, context = _pair()
    invalid_locale = context.model_copy(
        update={
            "request_context": context.request_context.model_copy(update={"locale": "xx-XX"}),
        }
    )
    invalid_device = context.model_copy(
        update={
            "request_context": context.request_context.model_copy(update={"device": "tv"}),
        }
    )
    assert evaluate_eligibility(experience, user, invalid_locale).reason_code is EligibilityReasonCode.LOCALE_NOT_SUPPORTED
    assert evaluate_eligibility(experience, user, invalid_device).reason_code is EligibilityReasonCode.DEVICE_NOT_SUPPORTED


def test_consent_denied_allows_safe_non_personalized_result():
    user, experience, context = _pair("user-008", "exp-002")
    decision = evaluate_eligibility(experience, user, context)
    assert decision.eligible is True
    assert decision.personalization_allowed is False
    assert decision.reason_code is EligibilityReasonCode.PERSONALIZATION_CONSENT_DENIED


def test_consent_can_be_required_without_becoming_a_model_score():
    user, experience, context = _pair("user-008")
    constraints = EligibilityConstraints(
        tenant_id=user.tenant_id,
        locale=user.locale,
        device=CatalogDevice.DESKTOP,
        age_rating_limit=user.age_rating_limit,
        personalization_requested=True,
        require_personalization=True,
    )
    decision = evaluate_eligibility(experience, user, context, constraints)
    assert decision.eligible is False
    assert decision.reason_code is EligibilityReasonCode.PERSONALIZATION_CONSENT_REQUIRED


def test_extra_blank_invalid_and_mutation_inputs_are_rejected():
    record = _load("experiences.json")[0]
    with pytest.raises(ValidationError):
        ExperienceRecord.model_validate({**record, "experience_id": " "})
    with pytest.raises(ValidationError):
        UserProfile.model_validate({**_load("users.json")[0], "locale": "xx-XX"})
    with pytest.raises(ValidationError):
        UserProfile.model_validate({**_load("users.json")[0], "unexpected": True})
    with pytest.raises(ValidationError):
        ExperienceRecord.model_validate({**record, "devices": ["console"]})
    with pytest.raises((TypeError, ValidationError)):
        ExperienceRecord.model_validate(record).title = "changed"


def test_history_none_uses_safe_fallback_reason():
    user, experience, context = _pair("user-007", "exp-002")
    decision = evaluate_eligibility(experience, user, context)
    assert decision.reason_code is EligibilityReasonCode.SAFE_CATALOG_FALLBACK
