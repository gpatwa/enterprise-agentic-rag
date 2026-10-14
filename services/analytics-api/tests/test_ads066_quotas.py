"""ADS-066: per-tenant quotas, SLOs, cost attribution, and alerts; noisy-neighbour and denial-of-wallet scenarios pass."""

from __future__ import annotations

import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from reference_stack.stack import build_stack

from app.quotas import (
    CONCURRENCY_LIMITED,
    COST_EXHAUSTED,
    RATE_LIMITED,
    FakeClock,
    QuotaGuardedService,
    QuotaManager,
    SloTracker,
    simulate,
)
from app.runtime.analyze_service import ServiceError
from packages.platform_contracts.quotas import QuotaPolicy, SloObjective, TenantQuota

SERVICE = Path(__file__).resolve().parent.parent
PROPOSED = SERVICE / "quotas/quota-policy.proposed.json"
PURPOSE = "analytics"


def _policy(**quota) -> QuotaPolicy:
    base = {
        "requests_per_minute": 60,
        "burst": 20,
        "max_concurrent_runs": 4,
        "daily_cost_units": 10_000,
        "warn_fraction": 0.8,
    }
    base.update(quota)
    return QuotaPolicy(
        policy_version="test",
        default=TenantQuota(**base),
        slo=SloObjective(success_target=0.99, p95_latency_seconds=8),
        approval={"status": "proposed"},
    )


# ---- policy ----


def test_the_repository_policy_is_valid_and_not_approved_and_tenants_can_override():
    policy = QuotaPolicy.model_validate_json(PROPOSED.read_text())
    assert policy.approval.status == "proposed" and policy.approval.approved_by is None
    assert policy.quota_for("anyone") == policy.default
    tight = TenantQuota(requests_per_minute=1, burst=1, max_concurrent_runs=1, daily_cost_units=1)
    overridden = policy.model_copy(update={"tenants": {"tenant-small": tight}})
    assert overridden.quota_for("tenant-small") == tight and overridden.quota_for("tenant-big") == policy.default
    with pytest.raises(ValidationError, match="who approved"):
        QuotaPolicy(policy_version="v", default=policy.default, slo=policy.slo, approval={"status": "approved"})
    with pytest.raises(ValidationError, match="fast window"):
        SloObjective(success_target=0.99, p95_latency_seconds=1, fast_window_seconds=600, slow_window_seconds=60)
    with pytest.raises(ValidationError):
        TenantQuota(requests_per_minute=0, burst=1, max_concurrent_runs=1, daily_cost_units=1)


# ---- admission ----


def test_the_rate_limit_is_a_token_bucket_that_refills_with_time_per_tenant():
    clock = FakeClock()
    manager = QuotaManager(_policy(burst=3, requests_per_minute=60, max_concurrent_runs=100), clock=clock)
    assert [manager.admit("a").allowed for _ in range(3)] == [True, True, True]
    denied = manager.admit("a")
    assert (denied.allowed, denied.code) == (False, RATE_LIMITED) and denied.retry_after_seconds == 1
    assert manager.admit("b").allowed  # another tenant's bucket is untouched
    clock.set(clock.now + timedelta(seconds=2))
    assert manager.admit("a").allowed and manager.admit("a").allowed and not manager.admit("a").allowed
    clock.set(clock.now + timedelta(hours=1))
    assert [manager.admit("a").allowed for _ in range(4)] == [True, True, True, False]  # refill is capped at the burst


def test_concurrency_is_capped_and_released_and_never_goes_negative():
    manager = QuotaManager(_policy(max_concurrent_runs=2, burst=100), clock=FakeClock())
    assert manager.admit("a").allowed and manager.admit("a").allowed
    blocked = manager.admit("a")
    assert (blocked.allowed, blocked.code) == (False, CONCURRENCY_LIMITED)
    manager.finish("a")
    assert manager.admit("a").allowed
    for _ in range(5):
        manager.finish("a")
    assert manager.usage("a").in_flight == 0


def test_concurrency_holds_under_real_threads():
    manager = QuotaManager(_policy(max_concurrent_runs=4, burst=1_000, requests_per_minute=60_000))
    peak, current, lock, denied = [0], [0], threading.Lock(), [0]

    def worker() -> None:
        for _ in range(20):
            if manager.admit("a").allowed:
                with lock:
                    current[0] += 1
                    peak[0] = max(peak[0], current[0])
                time.sleep(0.001)
                with lock:
                    current[0] -= 1
                manager.finish("a")
            else:
                denied[0] += 1

    threads = [threading.Thread(target=worker) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] <= 4 and manager.usage("a").in_flight == 0 and denied[0] > 0


# ---- cost: budget, attribution, reset, alerts ----


def test_the_daily_cost_budget_blocks_further_work_attributes_cost_once_and_resets_at_midnight_utc():
    clock = FakeClock()
    manager = QuotaManager(_policy(daily_cost_units=100, burst=100, max_concurrent_runs=100), clock=clock)
    for index, cost in enumerate((30, 30)):
        assert manager.admit("a").allowed
        manager.finish("a", run_ref=f"r{index}", cost_units=cost, purpose="analytics", dialect="duckdb")
    manager.admit("a")
    manager.finish("a", run_ref="r1", cost_units=30, purpose="analytics")  # the same run again: not double-counted
    usage = manager.usage("a")
    assert (
        usage.day_cost_units == 60
        and dict(usage.by_purpose) == {"analytics": 60}
        and dict(usage.by_dialect) == {"duckdb": 60}
    )
    manager.admit("a")
    manager.finish("a", run_ref="r2", cost_units=45, purpose="reporting")  # 105 >= 100
    refused = manager.admit("a")
    assert (refused.allowed, refused.code) == (False, COST_EXHAUSTED)
    assert 0 < refused.retry_after_seconds <= 86_400
    assert manager.admit("b").allowed  # nobody else pays for a's budget
    assert dict(manager.usage("a").by_purpose) == {"analytics": 60, "reporting": 45}
    clock.set(clock.now + timedelta(days=1))
    assert manager.admit("a").allowed and manager.usage("a").day_cost_units == 0


def test_cost_alerts_fire_once_per_condition_per_day_and_carry_runbooks():
    clock = FakeClock()
    manager = QuotaManager(_policy(daily_cost_units=100, burst=100, max_concurrent_runs=100), clock=clock)
    for index, cost in enumerate((50, 35, 20)):
        manager.admit("a")
        manager.finish("a", run_ref=f"r{index}", cost_units=cost)
    for _ in range(3):
        manager.admit("a")  # refused repeatedly: still one alert
    kinds = [(a.kind, a.severity) for a in manager.alerts]
    assert kinds == [("cost_budget_warning", "warning"), ("cost_budget_exhausted", "page")]
    assert {a.runbook_id for a in manager.alerts} == {"ops-cost-budget"} and {a.tenant_id for a in manager.alerts} == {
        "a"
    }
    clock.set(clock.now + timedelta(days=1))
    manager.admit("a")
    manager.finish("a", run_ref="r9", cost_units=90)
    assert [a.kind for a in manager.alerts][-1] == "cost_budget_warning" and len(manager.alerts) == 3


# ---- the load scenarios ----


def test_a_noisy_neighbour_is_throttled_without_touching_another_tenants_service():
    clock = FakeClock()
    manager = QuotaManager(_policy(burst=20, requests_per_minute=60, max_concurrent_runs=4), clock=clock)
    noisy = [
        (second + index / 50, "noisy", 2.0, 1.0) for second in range(10) for index in range(50)
    ]  # 50 requests/second
    quiet = [(second * 2.0, "quiet", 2.0, 1.0) for second in range(5)]  # one every two seconds
    result = simulate(manager, clock, noisy + quiet)
    assert result.admitted["quiet"] == 5 and not result.denied["quiet"]  # every quiet request was served
    assert result.peak_in_flight["noisy"] <= 4 and result.peak_in_flight["quiet"] <= 1
    assert (
        result.admitted["noisy"] <= 20 + 10 and sum(result.denied["noisy"].values()) >= 450
    )  # bounded by burst + rate
    assert set(result.denied["noisy"]) <= {RATE_LIMITED, CONCURRENCY_LIMITED}
    assert {a.tenant_id for a in manager.alerts} == {"noisy"}


def test_a_denial_of_wallet_stops_at_the_budget_and_other_tenants_keep_their_own():
    clock = FakeClock()
    manager = QuotaManager(
        _policy(burst=1_000, requests_per_minute=60_000, max_concurrent_runs=1_000, daily_cost_units=1_000), clock=clock
    )
    attack = [
        (index * 0.1, "victim-of-credential-theft", 0.05, 400.0) for index in range(200)
    ]  # expensive queries, relentlessly
    honest = [(index * 5.0, "honest", 0.05, 20.0) for index in range(10)]
    result = simulate(manager, clock, attack + honest)
    # Cost is only known after a run finishes, so a few runs already in flight can overshoot; the cap bounds it tightly.
    assert result.cost["victim-of-credential-theft"] <= 1_000 + 400 * 2
    assert (
        result.admitted["victim-of-credential-theft"] <= 4
        and result.denied["victim-of-credential-theft"][COST_EXHAUSTED] >= 190
    )
    assert result.admitted["honest"] == 10 and not result.denied["honest"]
    assert [a.kind for a in manager.alerts if a.tenant_id == "victim-of-credential-theft"][
        -1
    ] == "cost_budget_exhausted"
    assert not [a for a in manager.alerts if a.tenant_id == "honest"]


# ---- the real service behind the guard ----


def _guarded(tmp_path, policy, name="a"):
    stack = build_stack("duckdb", tmp_path / name)
    clock = FakeClock()
    quotas, slo = QuotaManager(policy, clock=clock), SloTracker(policy, clock=clock)
    calls = []
    service = stack.service()
    original = service.analyze
    service.analyze = lambda *a, **k: (calls.append(1), original(*a, **k))[1]
    return stack, QuotaGuardedService(service, quotas, slo, stack.evidence, dialect="duckdb"), quotas, slo, calls, clock


def _who(stack, user="requester", tenant="tenant-a"):
    return stack.verifier().verify(stack.token(user, tenant=tenant))


def test_the_guard_attributes_real_run_cost_and_a_wallet_attack_stops_executing_queries(tmp_path):
    stack, guarded, quotas, slo, calls, _ = _guarded(tmp_path, _policy())
    who = _who(stack)
    first = guarded.analyze(
        who, purpose=PURPOSE, idempotency_key="wallet-key-0000", request_text="Show monthly revenue"
    )
    assert first.state == "terminal"
    unit_cost = quotas.usage("tenant-a").day_cost_units
    assert unit_cost > 0 and dict(quotas.usage("tenant-a").by_dialect) == {"duckdb": unit_cost}

    capped = _policy(daily_cost_units=unit_cost * 2.5)
    stack, guarded, quotas, slo, calls, _ = _guarded(tmp_path, capped, name="capped")
    who, other = _who(stack), _who(stack, "outsider", "tenant-b")
    results = []
    for index in range(6):
        try:
            guarded.analyze(
                who, purpose=PURPOSE, idempotency_key=f"wallet-key-{index:04d}", request_text="Show monthly revenue"
            )
            results.append("ok")
        except ServiceError as exc:
            results.append((exc.status, exc.code))
    assert results == ["ok", "ok", "ok", (429, COST_EXHAUSTED), (429, COST_EXHAUSTED), (429, COST_EXHAUSTED)]
    assert (
        len(stack.executed_sql) == 3 and len(calls) == 3
    )  # exactly the three admitted runs executed; refused ones ran nothing
    assert quotas.admit(
        other.tenant_id
    ).allowed  # the reference stack serves one tenant's context; admission is per tenant
    kinds = [a.kind for a in quotas.alerts if a.tenant_id == "tenant-a"]
    assert kinds == ["cost_budget_warning", "cost_budget_exhausted"]


def test_the_guard_releases_slots_on_failure_meters_only_cost_bearing_calls_and_limits_before_running(tmp_path):
    stack, guarded, quotas, slo, calls, _ = _guarded(
        tmp_path, _policy(burst=2, requests_per_minute=60, max_concurrent_runs=1)
    )
    who = _who(stack)
    with pytest.raises(ServiceError) as bad_purpose:
        guarded.analyze(who, purpose="billing", idempotency_key="slot-key-00001", request_text="Show monthly revenue")
    assert bad_purpose.value.status == 403 and quotas.usage("tenant-a").in_flight == 0  # the slot came back
    run = guarded.analyze(who, purpose=PURPOSE, idempotency_key="slot-key-00002", request_text="Show monthly revenue")
    before = quotas.usage("tenant-a").admitted
    for _ in range(5):
        assert guarded.status(who, purpose=PURPOSE, run_id=run.run_id).state == "terminal"  # reads are not metered
    assert quotas.usage("tenant-a").admitted == before
    denied = []
    for index in range(3):
        try:
            guarded.analyze(
                who, purpose=PURPOSE, idempotency_key=f"burst-key-{index:04d}", request_text="Show monthly revenue"
            )
        except ServiceError as exc:
            denied.append((exc.status, exc.code))
    assert denied == [(429, RATE_LIMITED)] * 3  # the two earlier calls spent the burst of two
    assert len(calls) == 2  # throttled requests never reached the service


# ---- SLOs ----


def test_slo_burn_rates_page_on_a_fast_burn_ticket_on_a_slow_one_and_stay_quiet_on_little_traffic():
    clock = FakeClock()
    slo = SloTracker(_policy(), clock=clock)
    for _ in range(19):
        slo.record("a", ok=False, latency_seconds=1)
    assert slo.evaluate("a") == []  # nineteen requests are below the minimum: not an alert
    slo.record("a", ok=False, latency_seconds=1)
    kinds = {a.kind: a for a in slo.evaluate("a")}
    assert set(kinds) == {"slo_fast_burn", "slo_slow_burn"} and kinds["slo_fast_burn"].severity == "page"
    assert kinds["slo_fast_burn"].value == pytest.approx(100.0) and {a.runbook_id for a in kinds.values()} == {
        "ops-slo-burn"
    }
    clock.set(clock.now + timedelta(seconds=400))  # the fast window moves on; the hour still remembers
    assert {a.kind for a in slo.evaluate("a")} == {"slo_slow_burn"}
    clock.set(clock.now + timedelta(hours=2))
    assert slo.evaluate("a") == []  # everything has aged out


def test_a_healthy_tenant_and_user_caused_refusals_do_not_burn_the_budget_and_slow_runs_raise_a_latency_alert(tmp_path):
    clock = FakeClock()
    slo = SloTracker(_policy(), clock=clock)
    for _ in range(100):
        slo.record("healthy", ok=True, latency_seconds=0.5)
    assert slo.evaluate("healthy") == [] and slo.burn_rate("healthy", 300) == (0.0, 100)
    for index in range(100):
        slo.record("slow", ok=True, latency_seconds=12.0 if index % 5 else 1.0)
    alerts = slo.evaluate("slow")
    assert (
        [a.kind for a in alerts] == ["slo_latency"]
        and alerts[0].value == 12.0
        and alerts[0].runbook_id == "ops-slo-latency"
    )
    stack, guarded, quotas, tracker, calls, _ = _guarded(tmp_path, _policy())
    who = _who(stack)
    with pytest.raises(ServiceError):
        guarded.analyze(who, purpose="billing", idempotency_key="slo-key-000001", request_text="Show monthly revenue")
    assert tracker.burn_rate("tenant-a", 300) == (0.0, 1)  # a 403 the caller caused is not a system failure
    guarded.analyze(who, purpose=PURPOSE, idempotency_key="slo-key-000002", request_text="Show monthly revenue")
    assert tracker.burn_rate("tenant-a", 300) == (0.0, 2)


def test_quota_state_holds_counts_and_costs_only_and_nothing_mounts_it_yet(tmp_path):
    manager = QuotaManager(_policy(), clock=FakeClock())
    manager.admit("a")
    manager.finish("a", run_ref="r", cost_units=3, purpose="analytics")
    dumped = repr(manager.usage("a")) + repr(manager.alerts)
    for forbidden in ("user", "request_text", "SELECT", "token"):
        assert forbidden not in dumped
    for path in (SERVICE / "app/main.py", SERVICE / "app/api_v2.py"):
        assert "app.quotas" not in path.read_text(), path.name
