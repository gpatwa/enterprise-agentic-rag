import pytest

from app.resolution.models import ConfidenceLevel, SupportIntent, SupportIntentType
from app.resolution.routing import (
    ModelRoute,
    QueryPlanCache,
    ResolutionBudget,
    RoutingPolicy,
    choose_route,
    make_cache_key,
    route_query_plan,
)


def intent(kind=SupportIntentType.INCIDENT, confidence=ConfidenceLevel.HIGH):
    return SupportIntent(intent=kind, reason="clear", confidence=confidence)


def test_cache_key_is_tenant_isolated_and_opaque():
    key = make_cache_key("tenant-a", intent())
    assert key != make_cache_key("tenant-b", intent())
    assert "tenant-a" not in key and "clear" not in key
    assert "principal" not in key


def test_cache_expires_and_evicts_oldest_deterministically():
    now = [0.0]
    cache = QueryPlanCache(ttl_seconds=5, max_entries=2, clock=lambda: now[0])
    cache.put("a", 1)
    cache.put("b", 2)
    cache.put("c", 3)
    assert cache.get("a") is None and cache.get("b") == 2
    now[0] = 5
    assert len(cache) == 0


def test_route_selection_and_kill_switch():
    assert choose_route(intent()) == ModelRoute.CHEAP
    assert choose_route(intent(confidence=ConfidenceLevel.LOW)) == ModelRoute.STRONG
    cache = QueryPlanCache()
    assert route_query_plan("t", intent(), cache, policy=RoutingPolicy(kill_switch=True))[0] == ModelRoute.DETERMINISTIC


@pytest.mark.parametrize("field", ["max_query_variants", "max_input_tokens", "max_output_tokens", "timeout_seconds"])
def test_invalid_budget_values_fail(field):
    with pytest.raises(ValueError):
        ResolutionBudget(**{field: 0})
    with pytest.raises(ValueError):
        ResolutionBudget(**{field: -1})
