import pytest

from app.resolution.telemetry import (
    build_telemetry,
    estimated_cost_usd,
    try_build_telemetry,
)


def test_build_is_deterministic_and_redacted():
    attrs = build_telemetry(
        latency=12, input_tokens=10, output_tokens=4, estimated_cost=0.02,
        route="cheap", stage="intent", model_version="m1", prompt_version="p1",
        policy_version="policy1", fallback_reason="timeout",
        quality={"claims": 2, "supported_claims": 1},
    )
    assert list(attrs) == sorted(attrs)
    assert "private ticket" not in str(attrs)
    assert attrs["quality_claims"] == 2


@pytest.mark.parametrize("value", [-1, float("inf"), float("nan")])
def test_rejects_unbounded_numeric_values(value):
    with pytest.raises((TypeError, ValueError)):
        build_telemetry(latency=value, input_tokens=1, output_tokens=1, estimated_cost=0,
                        route="r", stage="s", model_version="m", prompt_version="p", policy_version="v")


def test_cost_is_count_based_and_raw_fields_are_not_accepted():
    assert estimated_cost_usd(input_tokens=2, output_tokens=3, input_rate=.1, output_rate=.2) == .8
    assert try_build_telemetry(prompt="raw prompt") is None
