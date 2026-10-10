from __future__ import annotations

import pytest


def test_opensearch_is_disabled_and_safe_by_default():
    from app.config import Settings

    settings = Settings(_env_file=None)

    assert settings.OPENSEARCH_ENABLED is False
    assert settings.get_opensearch_url() == "http://opensearch:9200"
    settings.validate_opensearch_settings()


def test_opensearch_development_settings_support_basic_auth_and_custom_endpoint():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        ENV="dev",
        OPENSEARCH_ENABLED=True,
        OPENSEARCH_URL="http://localhost:9200/",
        OPENSEARCH_AUTH_MODE="basic",
        OPENSEARCH_USERNAME="local-user",
        OPENSEARCH_PASSWORD="local-password",
        OPENSEARCH_POOL_MAXSIZE=4,
    )

    assert settings.get_opensearch_url() == "http://localhost:9200"
    settings.validate_opensearch_settings()


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"OPENSEARCH_URL": "http://search.internal:9200"}, "HTTPS"),
        ({"OPENSEARCH_VERIFY_CERTS": False}, "certificate verification"),
        ({"OPENSEARCH_USERNAME": None, "OPENSEARCH_PASSWORD": None}, "username and password"),
        ({"OPENSEARCH_AUTH_MODE": "api_key", "OPENSEARCH_API_KEY": None}, "api_key OpenSearch auth"),
        ({"OPENSEARCH_AUTH_MODE": "unsupported"}, "one of"),
    ],
)
def test_opensearch_production_validation_fails_closed(overrides, message):
    from app.config import Settings

    values = {
        "_env_file": None,
        "ENV": "prod",
        "OPENSEARCH_ENABLED": True,
        "OPENSEARCH_URL": "https://search.internal:9200",
        "OPENSEARCH_AUTH_MODE": "basic",
        "OPENSEARCH_USERNAME": "user",
        "OPENSEARCH_PASSWORD": "password",
    }
    values.update(overrides)
    settings = Settings(**values)

    with pytest.raises(ValueError, match=message):
        settings.validate_opensearch_settings()


def test_opensearch_api_key_auth_validates():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        ENV="prod",
        OPENSEARCH_ENABLED=True,
        OPENSEARCH_URL="https://search.internal:9200",
        OPENSEARCH_AUTH_MODE="api_key",
        OPENSEARCH_API_KEY="encoded-api-key",
    )

    settings.validate_opensearch_settings()
