from __future__ import annotations


def test_otel_endpoint_prefers_app_native_name():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        OTEL_ENDPOINT="http://native:4317",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://standard:4317",
    )

    assert settings.get_otel_endpoint() == "http://native:4317"


def test_otel_endpoint_accepts_standard_otlp_alias():
    from app.config import Settings

    settings = Settings(
        _env_file=None,
        OTEL_ENDPOINT=None,
        OTEL_EXPORTER_OTLP_ENDPOINT="http://standard:4317",
    )

    assert settings.get_otel_endpoint() == "http://standard:4317"
