"""M7-H5: one bounded retry for transient model and warehouse failures, and a circuit breaker that fails fast."""

from __future__ import annotations

import pytest

from app.resilience.retry import (
    CircuitBreaker,
    DependencyUnavailable,
    ResilientGateway,
    ResilientModelClient,
    RetryPolicy,
    call_with_retry,
)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _flaky(failures: int, exc: type[BaseException] = TimeoutError):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] <= failures:
            raise exc("transient")
        return "ok"

    return fn, calls


def test_one_transient_failure_is_retried_and_a_second_one_is_raised():
    fn, calls = _flaky(1)
    assert call_with_retry(fn, sleep=lambda s: None) == "ok" and calls["n"] == 2
    fn, calls = _flaky(5)
    with pytest.raises(TimeoutError):
        call_with_retry(fn, sleep=lambda s: None)
    assert calls["n"] == 2  # bounded: one try plus one retry


@pytest.mark.parametrize("exc", [ValueError, KeyError, RuntimeError])
def test_a_non_transient_error_is_never_retried(exc):
    fn, calls = _flaky(1, exc)
    with pytest.raises(exc):
        call_with_retry(fn, sleep=lambda s: None)
    assert calls["n"] == 1


def test_the_backoff_is_applied_between_attempts_only():
    waits = []
    fn, _ = _flaky(5, ConnectionError)
    with pytest.raises(ConnectionError):
        call_with_retry(fn, policy=RetryPolicy(attempts=3, backoff_seconds=0.5), sleep=waits.append)
    assert waits == [0.5, 0.5]


def test_the_breaker_opens_after_consecutive_failures_fails_fast_then_half_opens():
    clock = Clock()
    breaker = CircuitBreaker("model", failure_threshold=3, cooldown_seconds=30, clock=clock)
    fn, calls = _flaky(100, ConnectionError)
    for _ in range(3):
        with pytest.raises(ConnectionError):
            call_with_retry(fn, policy=RetryPolicy(attempts=1), breaker=breaker, sleep=lambda s: None)
    assert breaker.state == "open"
    with pytest.raises(DependencyUnavailable):
        call_with_retry(fn, policy=RetryPolicy(attempts=1), breaker=breaker, sleep=lambda s: None)
    assert calls["n"] == 3  # the open breaker did not call the dependency
    clock.now = 31
    assert breaker.state == "half_open"
    with pytest.raises(ConnectionError):  # the trial call fails: open again for a full cooldown
        call_with_retry(fn, policy=RetryPolicy(attempts=1), breaker=breaker, sleep=lambda s: None)
    assert breaker.state == "open"
    clock.now = 62
    healthy, _ = _flaky(0)
    assert call_with_retry(healthy, policy=RetryPolicy(attempts=1), breaker=breaker) == "ok"
    assert breaker.state == "closed"


def test_a_success_resets_the_failure_count():
    breaker = CircuitBreaker("w", failure_threshold=2, cooldown_seconds=10, clock=Clock())
    breaker.record_failure()
    breaker.record_success()
    breaker.record_failure()
    assert breaker.state == "closed"


def test_policy_and_breaker_reject_unsafe_settings():
    with pytest.raises(ValueError):
        RetryPolicy(attempts=0)
    with pytest.raises(ValueError):
        RetryPolicy(attempts=10)
    with pytest.raises(ValueError):
        CircuitBreaker("x", failure_threshold=0)


def test_the_wrappers_retry_the_model_and_the_gateway():
    class Model:
        calls = 0

        def complete_json(self, *, prompt, schema, max_tokens):
            Model.calls += 1
            if Model.calls == 1:
                raise TimeoutError("slow")
            return {"ok": True}

    assert ResilientModelClient(Model(), sleep=lambda s: None).complete_json(prompt="p", schema={}, max_tokens=1) == {
        "ok": True
    }

    class Gateway:
        dialect = "duckdb"
        executed = 0

        def estimate(self, plan):
            return 1.0

        def execute(self, plan, **kwargs):
            Gateway.executed += 1
            raise ConnectionError("down")

    wrapped = ResilientGateway(Gateway(), sleep=lambda s: None)
    assert wrapped.dialect == "duckdb" and wrapped.estimate(object()) == 1.0
    with pytest.raises(ConnectionError):
        wrapped.execute(object())
    assert Gateway.executed == 2


def test_the_reference_stack_retries_a_flaky_model_once(tmp_path):
    from unittest import mock

    from reference_stack import stack as stack_module
    from reference_stack.stack import build_stack

    real = stack_module.ScriptedIntentClient
    calls = {"n": 0}

    class Flaky:
        def __init__(self, *args, **kwargs):
            self.inner = real(*args, **kwargs)

        def complete_json(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise TimeoutError("provider timed out")
            return self.inner.complete_json(**kwargs)

    stack = build_stack("duckdb", tmp_path)
    who = stack.verifier().verify(stack.token("requester"))
    with mock.patch.object(stack_module, "ScriptedIntentClient", Flaky):
        reply = stack.service().analyze(
            who, purpose="analytics", idempotency_key="retry-h5-000001", request_text="What is total revenue"
        )
    assert reply.outcome.outcome == "answer" and calls["n"] == 2
