import pytest
from pydantic import ValidationError

from app.config import DiscoverySettings, Environment, FeatureFlags, settings_from_env


def test_local_defaults_are_safe_and_model_paths_are_disabled() -> None:
    settings = DiscoverySettings()

    assert settings.environment is Environment.LOCAL
    assert settings.profile == "local"
    assert settings.fake_provider is True
    assert settings.no_model is True
    assert settings.features.lexical is True
    assert settings.features.vector is False
    assert settings.features.learned is False
    assert settings.features.llm is False


def test_explicit_fake_mode_can_be_loaded_from_environment() -> None:
    settings = settings_from_env(
        {
            "DISCOVERY_ENVIRONMENT": "test",
            "DISCOVERY_PROFILE": "test",
            "DISCOVERY_FAKE_PROVIDER": "true",
            "DISCOVERY_NO_MODEL": "on",
            "DISCOVERY_FEATURE_VECTOR": "1",
        }
    )

    assert settings.environment is Environment.TEST
    assert settings.fake_provider is True
    assert settings.no_model is True
    assert settings.features.vector is True


def test_production_requires_operational_safeguards() -> None:
    with pytest.raises(ValidationError, match="production"):
        DiscoverySettings(environment=Environment.PRODUCTION, profile="prod")


def test_bounds_and_feature_combinations_are_rejected() -> None:
    with pytest.raises(ValidationError):
        DiscoverySettings(port=0)
    with pytest.raises(ValidationError):
        DiscoverySettings(candidate_cap=1001)
    with pytest.raises(ValidationError):
        DiscoverySettings(request_timeout_seconds=0)
    with pytest.raises(ValidationError):
        FeatureFlags(lexical=False, vector=False, hybrid=True)
    with pytest.raises(ValidationError, match="no_model"):
        DiscoverySettings(features=FeatureFlags(learned=True))


def test_environment_parser_rejects_invalid_boolean() -> None:
    with pytest.raises(ValueError, match="DISCOVERY_NO_MODEL"):
        settings_from_env({"DISCOVERY_NO_MODEL": "sometimes"})


def test_redacted_serialization_contains_no_secret_fields() -> None:
    serialized = DiscoverySettings().redacted_dump()

    assert "secret" not in str(serialized).lower()
    assert "api_key" not in str(serialized).lower()
    assert serialized["fake_provider"] is True
