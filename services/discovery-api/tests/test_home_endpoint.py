"""Focused contract tests for the typed local home endpoint."""
import json
from pathlib import Path

from app.domain.models import ExperienceRecord, UserProfile
from app.routes.home import HomeRequest, LocalHomeService, home
from packages.platform_contracts.discovery import DiscoveryRequestContext

FIXTURE = Path(__file__).parent / "fixtures" / "golden"


def _context(**overrides):
    values = {
        "tenant_id": "tenant-orbit",
        "principal_id": "user-001",
        "request_id": "request-home-001",
        "purpose": "home",
        "locale": "en-US",
        "device": "web",
        "age": 16,
    }
    values.update(overrides)
    return DiscoveryRequestContext(**values)


def _user(*, consent_state="personalization_allowed", history_length="short"):
    return UserProfile(
        user_id="user-001", tenant_id="tenant-orbit", persona="short-history", locale="en-US",
        age_rating_limit="T", devices=("desktop",), history_length=history_length,
        preferences={"genres": ("adventure",), "themes": ("forest",)},
        consent_state=consent_state, synthetic=True,
    )


def _experiences():
    records = json.loads((FIXTURE / "experiences.json").read_text())[:2]
    return tuple(ExperienceRecord.model_validate(item) for item in records)


def _request(**overrides):
    return HomeRequest(context=_context(**overrides.pop("context", {})), **overrides)


def test_home_returns_personalized_results_and_lineage_token():
    response = LocalHomeService(_experiences(), (_user(),)).home(_request())

    assert response.error is None
    assert response.personalization_allowed is True
    assert response.results
    assert response.results[0].source == "personalized"
    response.impression_token.validate_for(_context())
    assert response.decision_trace is not None
    assert all("preferences" not in item.model_dump() for item in response.results)


def test_denied_consent_uses_safe_diverse_fallback():
    response = LocalHomeService(_experiences(), (_user(consent_state="personalization_denied"),)).home(_request())

    assert response.error is None
    assert response.fallback is True
    assert response.personalization_allowed is False
    assert response.persona.value == "no-personalization"
    assert response.results
    assert response.results[0].source == "safe_catalog_fallback"
    assert "personalization_consent_denied" in response.reasons


def test_no_history_uses_safe_fallback_and_respects_blocked_ids():
    service = LocalHomeService(_experiences(), (_user(history_length="none"),))
    response = service.home(HomeRequest(context=_context(), blocked_ids=("exp-001",), page_size=1))

    assert response.fallback is True
    assert response.personalization_allowed is False
    assert all(item.experience_id != "exp-001" for item in response.results)
    assert "no_history" in response.reasons


def test_missing_profile_fails_closed_without_token():
    response = LocalHomeService(_experiences(), ()).home(_request())

    assert response.error is not None
    assert response.error.code == "missing_context"
    assert response.results == ()
    assert response.impression_token is None


def test_fastapi_handler_uses_configured_provider(monkeypatch):
    monkeypatch.setattr("app.routes.home.service", LocalHomeService(_experiences(), (_user(),)))
    response = home(_request(page_size=1))

    assert len(response.results) == 1
    assert response.request_id == "request-home-001"
